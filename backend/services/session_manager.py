from __future__ import annotations

import asyncio
import json
import logging
import os
import pty
import re
import signal
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from config import CLAUDE_BIN, SESSIONS_DIR, LOGS_DIR

logger = logging.getLogger(__name__)

SESSIONS_FILE = SESSIONS_DIR / "sessions.json"

# Patterns that indicate Claude is waiting for user input (interactive prompts)
PROMPT_PATTERNS = [
    re.compile(r"Do you trust", re.IGNORECASE),
    re.compile(r"Allow .+\?", re.IGNORECASE),
    re.compile(r"\[Y/n\]", re.IGNORECASE),
    re.compile(r"\[y/N\]", re.IGNORECASE),
    re.compile(r"accept the workspace trust", re.IGNORECASE),
    re.compile(r"review and accept", re.IGNORECASE),
    re.compile(r"Permission requested", re.IGNORECASE),
    re.compile(r"Approve\?", re.IGNORECASE),
]

# Patterns that indicate Claude exited with an error (non-interactive)
ERROR_PATTERNS = [
    re.compile(r"Error: Workspace not trusted", re.IGNORECASE),
    re.compile(r"Error:", re.IGNORECASE),
]

# In-memory session tracking
_sessions: Dict[str, SessionInfo] = {}
# Track PTY file descriptors for writing back responses
_pty_masters: Dict[str, int] = {}
# Track log file handles
_log_handles: Dict[str, object] = {}
# Callback for prompt notifications (set by telegram bot)
_prompt_callback: Optional[Callable] = None


def set_prompt_callback(callback: Callable) -> None:
    """Register a callback for when a session blocks on a prompt.
    Signature: callback(session_id, project_name, prompt_text)
    """
    global _prompt_callback
    _prompt_callback = callback


@dataclass
class SessionInfo:
    session_id: str
    project_name: str
    project_path: str
    pid: int
    started_at: str
    log_file: str
    status: str = "running"  # running, blocked, dead
    blocked_prompt: str = ""

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["alive"] = _is_pid_alive(self.pid)
        elapsed = (datetime.utcnow() - datetime.fromisoformat(self.started_at)).total_seconds()
        d["uptime_seconds"] = int(elapsed)
        return d


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _save_sessions() -> None:
    data = {sid: asdict(s) for sid, s in _sessions.items()}
    SESSIONS_FILE.write_text(json.dumps(data, indent=2))


def _load_sessions() -> None:
    if not SESSIONS_FILE.exists():
        return
    try:
        data = json.loads(SESSIONS_FILE.read_text())
        for sid, info in data.items():
            if _is_pid_alive(info["pid"]):
                _sessions[sid] = SessionInfo(**info)
    except (json.JSONDecodeError, KeyError, TypeError):
        pass


def recover_sessions() -> int:
    _load_sessions()
    dead = [sid for sid, s in _sessions.items() if not _is_pid_alive(s.pid)]
    for sid in dead:
        del _sessions[sid]
    if dead:
        _save_sessions()
    return len(_sessions)


async def _monitor_pty_output(session_id: str, master_fd: int, log_fh) -> None:
    """Async reader that monitors PTY output for blocking prompts."""
    loop = asyncio.get_event_loop()
    buffer = ""

    def _read_chunk():
        try:
            return os.read(master_fd, 4096).decode("utf-8", errors="replace")
        except OSError:
            return None

    while True:
        chunk = await loop.run_in_executor(None, _read_chunk)
        if chunk is None:
            # PTY closed — process likely exited. Check buffer for error messages.
            session = _sessions.get(session_id)
            if session and buffer.strip():
                for pattern in ERROR_PATTERNS:
                    if pattern.search(buffer):
                        lines = buffer.strip().split("\n")
                        error_text = "\n".join(lines[-5:])
                        session.status = "dead"
                        session.blocked_prompt = error_text
                        _save_sessions()
                        logger.error(
                            f"Session {session_id} ({session.project_name}) exited with error: "
                            f"{error_text[:100]}"
                        )
                        if _prompt_callback:
                            try:
                                asyncio.create_task(
                                    _prompt_callback(session_id, session.project_name, f"[EXITED] {error_text}")
                                )
                            except Exception as e:
                                logger.error(f"Error callback failed: {e}")
                        break
            break

        # Write to log file
        try:
            log_fh.write(chunk)
            log_fh.flush()
        except (OSError, ValueError):
            pass

        # Check for blocking prompts
        buffer += chunk
        # Keep buffer manageable — only check last 2KB
        if len(buffer) > 2048:
            buffer = buffer[-2048:]

        for pattern in PROMPT_PATTERNS:
            if pattern.search(buffer):
                session = _sessions.get(session_id)
                if session and session.status != "blocked":
                    lines = buffer.strip().split("\n")
                    prompt_text = "\n".join(lines[-5:])
                    session.status = "blocked"
                    session.blocked_prompt = prompt_text
                    _save_sessions()
                    logger.warning(
                        f"Session {session_id} ({session.project_name}) blocked on prompt: "
                        f"{prompt_text[:100]}"
                    )
                    if _prompt_callback:
                        try:
                            asyncio.create_task(
                                _prompt_callback(session_id, session.project_name, prompt_text)
                            )
                        except Exception as e:
                            logger.error(f"Prompt callback error: {e}")
                    buffer = ""
                break


async def start_session(project_path: str, project_name: str, name: Optional[str] = None) -> SessionInfo:
    session_id = uuid.uuid4().hex[:12]
    display_name = name or project_name
    log_file = LOGS_DIR / f"{session_id}.log"

    env = {**os.environ, "PATH": f"/Users/b2/.local/bin:{os.environ.get('PATH', '')}"}

    # Spawn via PTY so we can monitor stdout for prompts
    master_fd, slave_fd = pty.openpty()

    log_fh = open(log_file, "w")
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_BIN,
            "remote-control",
            "--name", display_name,
            cwd=project_path,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
        )
    except Exception:
        os.close(master_fd)
        os.close(slave_fd)
        log_fh.close()
        raise

    # Close slave side in parent — child has it
    os.close(slave_fd)

    _pty_masters[session_id] = master_fd
    _log_handles[session_id] = log_fh

    session = SessionInfo(
        session_id=session_id,
        project_name=project_name,
        project_path=project_path,
        pid=proc.pid,
        started_at=datetime.utcnow().isoformat(),
        log_file=str(log_file),
    )
    _sessions[session_id] = session
    _save_sessions()

    # Start async PTY monitor
    asyncio.create_task(_monitor_pty_output(session_id, master_fd, log_fh))

    return session


async def respond_to_prompt(session_id: str, response: str) -> bool:
    """Send a response to a blocked session's prompt (e.g. 'y' or 'n')."""
    master_fd = _pty_masters.get(session_id)
    session = _sessions.get(session_id)
    if not master_fd or not session:
        return False

    try:
        os.write(master_fd, (response + "\n").encode())
        session.status = "running"
        session.blocked_prompt = ""
        _save_sessions()
        logger.info(f"Sent response '{response}' to session {session_id}")
        return True
    except OSError as e:
        logger.error(f"Failed to write to PTY for session {session_id}: {e}")
        return False


async def stop_session(session_id: str) -> bool:
    session = _sessions.get(session_id)
    if not session:
        return False

    try:
        os.kill(session.pid, signal.SIGTERM)
        for _ in range(10):
            await asyncio.sleep(0.5)
            if not _is_pid_alive(session.pid):
                break
        else:
            os.kill(session.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass

    # Close PTY master fd
    master_fd = _pty_masters.pop(session_id, None)
    if master_fd:
        try:
            os.close(master_fd)
        except OSError:
            pass

    # Close log file handle
    log_fh = _log_handles.pop(session_id, None)
    if log_fh:
        try:
            log_fh.close()
        except Exception:
            pass

    del _sessions[session_id]
    _save_sessions()
    return True


async def stop_all_sessions() -> int:
    """Stop all active sessions. Called on graceful shutdown."""
    count = 0
    for sid in list(_sessions.keys()):
        if await stop_session(sid):
            count += 1
    return count


def list_sessions() -> list:
    dead = [sid for sid, s in _sessions.items() if not _is_pid_alive(s.pid)]
    for sid in dead:
        # Clean up PTY/log handles for dead sessions
        master_fd = _pty_masters.pop(sid, None)
        if master_fd:
            try:
                os.close(master_fd)
            except OSError:
                pass
        log_fh = _log_handles.pop(sid, None)
        if log_fh:
            try:
                log_fh.close()
            except Exception:
                pass
        del _sessions[sid]
    if dead:
        _save_sessions()
    return [s.to_dict() for s in _sessions.values()]


def get_session(session_id: str) -> Optional[Dict]:
    s = _sessions.get(session_id)
    if not s:
        return None
    if not _is_pid_alive(s.pid):
        del _sessions[session_id]
        _save_sessions()
        return None
    return s.to_dict()
