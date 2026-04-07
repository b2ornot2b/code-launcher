from __future__ import annotations

import asyncio
import json
import os
import signal
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from config import CLAUDE_BIN, SESSIONS_DIR, LOGS_DIR

SESSIONS_FILE = SESSIONS_DIR / "sessions.json"

# In-memory session tracking
_sessions: Dict[str, SessionInfo] = {}
# Track open log file handles for cleanup
_log_handles: Dict[str, object] = {}


@dataclass
class SessionInfo:
    session_id: str
    project_name: str
    project_path: str
    pid: int
    started_at: str
    log_file: str

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
    except (json.JSONDecodeError, KeyError):
        pass


def recover_sessions() -> int:
    _load_sessions()
    dead = [sid for sid, s in _sessions.items() if not _is_pid_alive(s.pid)]
    for sid in dead:
        del _sessions[sid]
    if dead:
        _save_sessions()
    return len(_sessions)


async def start_session(project_path: str, project_name: str, name: Optional[str] = None) -> SessionInfo:
    session_id = uuid.uuid4().hex[:12]
    display_name = name or project_name
    log_file = LOGS_DIR / f"{session_id}.log"

    env = {**os.environ, "PATH": f"/Users/b2/.local/bin:{os.environ.get('PATH', '')}"}

    log_fh = open(log_file, "w")
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_BIN,
            "remote-control",
            "--name", display_name,
            cwd=project_path,
            stdout=log_fh,
            stderr=log_fh,
            env=env,
        )
    except Exception:
        log_fh.close()
        raise

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
    return session


async def stop_session(session_id: str) -> bool:
    session = _sessions.get(session_id)
    if not session:
        return False

    try:
        os.kill(session.pid, signal.SIGTERM)
        # Give it a moment to die gracefully
        for _ in range(10):
            await asyncio.sleep(0.5)
            if not _is_pid_alive(session.pid):
                break
        else:
            os.kill(session.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
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
