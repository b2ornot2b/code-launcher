from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

from config import CLAUDE_BIN, SESSIONS_DIR, LOGS_DIR

logger = logging.getLogger(__name__)

TMUX = "/opt/homebrew/bin/tmux"
SESSIONS_FILE = SESSIONS_DIR / "sessions.json"
TMUX_PREFIX = "ccl-"  # Claude Code Launcher prefix for tmux sessions

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

TRUST_ERROR = re.compile(r"Workspace not trusted", re.IGNORECASE)
WORKTREE_ERROR = re.compile(r"Worktree mode requires", re.IGNORECASE)

# In-memory session tracking
_sessions: Dict[str, SessionInfo] = {}
_prompt_callback: Optional[Callable] = None


def set_prompt_callback(callback: Callable) -> None:
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
    tmux_session: str = ""
    experiment: bool = False
    status: str = "running"  # running, blocked, dead
    blocked_prompt: str = ""

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["alive"] = _tmux_session_exists(self.tmux_session) if self.tmux_session else _is_pid_alive(self.pid)
        elapsed = (datetime.utcnow() - datetime.fromisoformat(self.started_at)).total_seconds()
        d["uptime_seconds"] = int(elapsed)
        return d


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _tmux_session_exists(name: str) -> bool:
    try:
        result = subprocess.run(
            [TMUX, "has-session", "-t", name],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _tmux_get_pane_pid(name: str) -> int:
    """Get the PID of the process running in a tmux session's pane."""
    try:
        result = subprocess.run(
            [TMUX, "list-panes", "-t", name, "-F", "#{pane_pid}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return 0


def _make_tmux_name(project_name: str, session_name: Optional[str] = None) -> str:
    """Generate tmux session name: ccl-<project>[-<name>]-<YYMMDDHHmmss>"""
    slug = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-")[:20]
    ts = datetime.utcnow().strftime("%y%m%d%H%M%S")
    if session_name:
        name_slug = re.sub(r"[^a-z0-9]+", "-", session_name.lower()).strip("-")[:15]
        return f"{TMUX_PREFIX}{slug}-{name_slug}-{ts}"
    return f"{TMUX_PREFIX}{slug}-{ts}"


def cleanup_stale_tmux() -> int:
    """Kill tmux sessions with our prefix that are dead (pane exited) or not tracked."""
    try:
        result = subprocess.run(
            [TMUX, "list-sessions", "-F", "#{session_name} #{?pane_dead,dead,alive}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return 0
    except Exception:
        return 0

    tracked_tmux = {s.tmux_session for s in _sessions.values()}
    killed = 0

    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.rsplit(" ", 1)
        name = parts[0]
        status = parts[1] if len(parts) > 1 else ""

        if not name.startswith(TMUX_PREFIX):
            continue

        # Kill if dead pane or not tracked by our session manager
        if status == "dead" or name not in tracked_tmux:
            try:
                subprocess.run(
                    [TMUX, "kill-session", "-t", name],
                    capture_output=True, timeout=5,
                )
                killed += 1
                logger.info(f"Cleaned up stale tmux session: {name}")
            except Exception:
                pass

    return killed


def _save_sessions() -> None:
    data = {sid: asdict(s) for sid, s in _sessions.items()}
    SESSIONS_FILE.write_text(json.dumps(data, indent=2))
    os.chmod(SESSIONS_FILE, 0o600)


def _load_sessions() -> None:
    if not SESSIONS_FILE.exists():
        return
    try:
        data = json.loads(SESSIONS_FILE.read_text())
        for sid, info in data.items():
            tmux_name = info.get("tmux_session", "")
            if tmux_name and _tmux_session_exists(tmux_name):
                _sessions[sid] = SessionInfo(**info)
            elif _is_pid_alive(info.get("pid", 0)):
                _sessions[sid] = SessionInfo(**info)
    except (json.JSONDecodeError, KeyError, TypeError):
        pass


def recover_sessions() -> int:
    _load_sessions()
    dead = []
    for sid, s in _sessions.items():
        if s.tmux_session and not _tmux_session_exists(s.tmux_session):
            dead.append(sid)
        elif not s.tmux_session and not _is_pid_alive(s.pid):
            dead.append(sid)
    for sid in dead:
        del _sessions[sid]
    if dead:
        _save_sessions()
    # Also clean up any orphaned tmux sessions with our prefix
    cleaned = cleanup_stale_tmux()
    if cleaned:
        logger.info(f"Cleaned up {cleaned} stale tmux session(s)")
    return len(_sessions)


async def _monitor_pipe_output(session_id: str, pipe_path: str) -> None:
    """Async reader that monitors tmux pipe-pane output for prompts and errors."""
    loop = asyncio.get_event_loop()
    buffer = ""

    # Wait for the pipe file to be created
    for _ in range(20):
        if os.path.exists(pipe_path):
            break
        await asyncio.sleep(0.25)

    def _read_chunk(fh):
        try:
            data = fh.read(4096)
            return data if data else None
        except (OSError, ValueError):
            return None

    try:
        # Open pipe in non-blocking read mode via a thread
        while True:
            session = _sessions.get(session_id)
            if not session:
                break
            if session.tmux_session and not _tmux_session_exists(session.tmux_session):
                break

            # Read whatever is available in the log file (tail -f style)
            log_file = session.log_file
            try:
                current_size = os.path.getsize(log_file)
                read_from = len(buffer)
                if current_size > read_from:
                    with open(log_file, "r", errors="replace") as f:
                        f.seek(read_from)
                        new_data = f.read()
                    if new_data:
                        buffer += new_data
                        if len(buffer) > 4096:
                            buffer = buffer[-4096:]

                        if session.status != "running":
                            await asyncio.sleep(1)
                            continue

                        # Check ERROR patterns first
                        error_matched = False
                        for pattern in ERROR_PATTERNS:
                            if pattern.search(buffer):
                                lines = buffer.strip().split("\n")
                                error_text = "\n".join(lines[-5:])
                                session.status = "dead"
                                session.blocked_prompt = error_text
                                _save_sessions()
                                is_trust = TRUST_ERROR.search(error_text)
                                is_worktree = WORKTREE_ERROR.search(error_text)
                                if is_trust:
                                    prefix = "[TRUST]"
                                elif is_worktree:
                                    prefix = "[WORKTREE]"
                                else:
                                    prefix = "[EXITED]"
                                logger.error(f"Session {session_id} error: {error_text[:100]}")
                                if _prompt_callback:
                                    try:
                                        asyncio.create_task(_prompt_callback(
                                            session_id, session.project_name,
                                            f"{prefix} {error_text}",
                                            project_path=session.project_path,
                                        ))
                                    except Exception as e:
                                        logger.error(f"Callback error: {e}")
                                buffer = ""
                                error_matched = True
                                break
                        if error_matched:
                            await asyncio.sleep(1)
                            continue

                        # Then check prompt patterns
                        for pattern in PROMPT_PATTERNS:
                            if pattern.search(buffer):
                                lines = buffer.strip().split("\n")
                                prompt_text = "\n".join(lines[-5:])
                                session.status = "blocked"
                                session.blocked_prompt = prompt_text
                                _save_sessions()
                                logger.warning(f"Session {session_id} blocked: {prompt_text[:100]}")
                                if _prompt_callback:
                                    try:
                                        asyncio.create_task(_prompt_callback(
                                            session_id, session.project_name, prompt_text,
                                            project_path=session.project_path,
                                        ))
                                    except Exception as e:
                                        logger.error(f"Callback error: {e}")
                                buffer = ""
                                break
            except (OSError, FileNotFoundError):
                pass

            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Monitor error for {session_id}: {e}")


async def start_session(project_path: str, project_name: str, name: Optional[str] = None, experiment: bool = False) -> SessionInfo:
    session_id = uuid.uuid4().hex[:12]
    display_name = name or project_name
    tmux_name = _make_tmux_name(project_name, name)
    log_file = LOGS_DIR / f"{session_id}.log"
    spawn_mode = "worktree" if experiment else "same-dir"

    claude_dir = str(Path(CLAUDE_BIN).parent)
    env_path = f"{claude_dir}:{os.environ.get('PATH', '')}"

    # Pass through OPENAI_API_KEY so sprint/opencode work inside sessions
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    env_exports = f"export PATH={shlex.quote(env_path)}; export HOME={shlex.quote(str(Path.home()))};"
    if openai_key:
        env_exports += f" export OPENAI_API_KEY={shlex.quote(openai_key)};"

    safe_name = shlex.quote(display_name)
    safe_log = shlex.quote(str(log_file))
    cmd = (
        f"{env_exports} "
        f"{CLAUDE_BIN} remote-control --name {safe_name} --spawn {spawn_mode} 2>&1 | tee -a {safe_log}; "
        f"echo '[SESSION EXITED]' >> {safe_log}; "
        f"sleep 5"
    )

    subprocess.run(
        [TMUX, "new-session", "-d", "-s", tmux_name, "-c", project_path, "bash", "-c", cmd],
        capture_output=True, timeout=10,
    )

    # Also set remain-on-exit so tmux session stays for inspection
    subprocess.run(
        [TMUX, "set-option", "-t", tmux_name, "remain-on-exit", "on"],
        capture_output=True, timeout=5,
    )

    # Get the PID of the shell in the tmux pane
    await asyncio.sleep(0.5)
    pid = _tmux_get_pane_pid(tmux_name)

    session = SessionInfo(
        session_id=session_id,
        project_name=project_name,
        project_path=project_path,
        pid=pid,
        started_at=datetime.utcnow().isoformat(),
        log_file=str(log_file),
        tmux_session=tmux_name,
        experiment=experiment,
    )
    _sessions[session_id] = session
    _save_sessions()

    # Start output monitor
    asyncio.create_task(_monitor_pipe_output(session_id, str(log_file)))

    return session


async def respond_to_prompt(session_id: str, response: str) -> bool:
    """Send a response to a blocked session's prompt via tmux send-keys."""
    session = _sessions.get(session_id)
    if not session or not session.tmux_session:
        return False
    if not _tmux_session_exists(session.tmux_session):
        return False

    try:
        subprocess.run(
            [TMUX, "send-keys", "-t", session.tmux_session, response, "Enter"],
            capture_output=True, timeout=5,
        )
        session.status = "running"
        session.blocked_prompt = ""
        _save_sessions()
        logger.info(f"Sent '{response}' to tmux session {session.tmux_session}")
        return True
    except Exception as e:
        logger.error(f"Failed to send keys to {session.tmux_session}: {e}")
        return False


async def trust_and_launch(project_path: str, project_name: str, name: Optional[str] = None) -> SessionInfo:
    """Trust a workspace via tmux, then re-launch as remote-control."""
    tmux_name = "claude-trust-tmp"
    claude_dir = str(Path(CLAUDE_BIN).parent)
    env_path = f"{claude_dir}:{os.environ.get('PATH', '')}"
    trust_log = LOGS_DIR / "trust_tmp.log"
    trust_log.write_text("")

    # Don't pipe through tee — the trust dialog needs a real TTY
    # Use tmux pipe-pane instead (captures output without breaking TTY)
    cmd = f"export PATH={shlex.quote(env_path)}; exec {CLAUDE_BIN}"

    # Kill any leftover trust session
    subprocess.run([TMUX, "kill-session", "-t", tmux_name], capture_output=True)
    await asyncio.sleep(0.5)

    # Launch interactive claude with real TTY in tmux
    subprocess.run(
        [TMUX, "new-session", "-d", "-s", tmux_name, "-c", project_path, "bash", "-c", cmd],
        capture_output=True, timeout=10,
    )

    # pipe-pane captures output without breaking the TTY
    subprocess.run(
        [TMUX, "pipe-pane", "-t", tmux_name, f"cat >> {trust_log}"],
        capture_output=True, timeout=5,
    )

    # Monitor for trust dialog and send Enter
    trust_sent = False
    for _ in range(40):  # max 20 seconds
        await asyncio.sleep(0.5)

        if not _tmux_session_exists(tmux_name):
            logger.warning("Trust tmux session died before trust could be sent")
            break

        try:
            content = trust_log.read_text(errors="replace")
        except OSError:
            continue

        if not trust_sent and re.search(r"Enter.*confirm", content):
            await asyncio.sleep(0.5)
            subprocess.run(
                [TMUX, "send-keys", "-t", tmux_name, "", "Enter"],
                capture_output=True, timeout=5,
            )
            logger.info(f"Sent Enter to accept trust for {project_name}")
            trust_sent = True

        if trust_sent:
            await asyncio.sleep(2)
            break

    # Kill the trust session
    subprocess.run([TMUX, "kill-session", "-t", tmux_name], capture_output=True)
    logger.info(f"Trust flow complete for {project_name} (sent={trust_sent})")

    # Clean up any dead tmux sessions for this project before re-launching
    cleanup_stale_tmux()

    # Now launch the actual remote-control session
    return await start_session(project_path, project_name, name)


async def stop_session(session_id: str) -> bool:
    session = _sessions.get(session_id)
    if not session:
        return False

    if session.tmux_session:
        subprocess.run(
            [TMUX, "kill-session", "-t", session.tmux_session],
            capture_output=True, timeout=5,
        )
    else:
        # Fallback for legacy sessions without tmux
        try:
            os.kill(session.pid, 14)  # SIGTERM
        except (OSError, ProcessLookupError):
            pass

    del _sessions[session_id]
    _save_sessions()
    return True


async def stop_all_sessions() -> int:
    count = 0
    for sid in list(_sessions.keys()):
        if await stop_session(sid):
            count += 1
    return count


def list_sessions() -> list:
    dead = []
    for sid, s in _sessions.items():
        if s.tmux_session and not _tmux_session_exists(s.tmux_session):
            dead.append(sid)
        elif not s.tmux_session and not _is_pid_alive(s.pid):
            dead.append(sid)
    for sid in dead:
        del _sessions[sid]
    if dead:
        _save_sessions()
        cleanup_stale_tmux()
    return [s.to_dict() for s in _sessions.values()]


def get_session(session_id: str) -> Optional[Dict]:
    s = _sessions.get(session_id)
    if not s:
        return None
    alive = _tmux_session_exists(s.tmux_session) if s.tmux_session else _is_pid_alive(s.pid)
    if not alive:
        del _sessions[session_id]
        _save_sessions()
        return None
    return s.to_dict()
