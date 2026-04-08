from __future__ import annotations

import asyncio
import logging
import os
import random
import secrets
import signal
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

TTYD_BIN = "/opt/homebrew/bin/ttyd"
TMUX_BIN = "/opt/homebrew/bin/tmux"
PORT_RANGE = (9000, 9999)
DEFAULT_TIMEOUT = 1800  # 30 minutes

_terminals: Dict[str, TerminalInfo] = {}


@dataclass
class TerminalInfo:
    terminal_id: str
    project_name: str
    project_path: str
    port: int
    credential: str
    url: str
    tmux_session: str
    pid: int
    started_at: str
    attach_mode: bool = False

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["alive"] = _is_pid_alive(self.pid)
        return d


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _get_host_ip() -> str:
    """Get the best IP for terminal URLs. Prefers Tailscale, falls back to LAN."""
    import socket
    # Try Tailscale (100.x.x.x)
    try:
        for line in subprocess.run(
            ["ifconfig"], capture_output=True, text=True, timeout=5,
        ).stdout.split("\n"):
            line = line.strip()
            if line.startswith("inet 100."):
                return line.split()[1]
    except Exception:
        pass

    # Fall back to hostname resolution or LAN IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _find_available_port() -> int:
    """Find an available port in the range."""
    import socket
    for _ in range(50):
        port = random.randint(*PORT_RANGE)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No available port found")


async def _auto_kill(terminal_id: str, pid: int, timeout: int) -> None:
    """Kill ttyd after timeout."""
    await asyncio.sleep(timeout)
    terminal = _terminals.get(terminal_id)
    if terminal and _is_pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info(f"Terminal {terminal_id} killed after {timeout}s timeout")
        except OSError:
            pass
        _terminals.pop(terminal_id, None)


async def start_terminal(
    project_path: str,
    project_name: str,
    tmux_session: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> TerminalInfo:
    """Start a web terminal for a project.

    If tmux_session is provided, attaches to that existing session.
    Otherwise creates a new tmux session in the project directory.
    """
    terminal_id = secrets.token_hex(6)
    port = _find_available_port()
    credential = secrets.token_urlsafe(16)
    host_ip = _get_host_ip()

    if tmux_session:
        # Attach to existing session
        shell_cmd = f"{TMUX_BIN} attach -t {tmux_session}"
        attach_mode = True
        tmux_name = tmux_session
    else:
        # New session in project dir
        ts = datetime.utcnow().strftime("%y%m%d%H%M%S")
        import re
        slug = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-")[:20]
        tmux_name = f"ccl-{slug}-term-{ts}"
        shell_cmd = f"{TMUX_BIN} new-session -A -s {tmux_name} -c {project_path}"
        attach_mode = False

    # Use token as base-path — no auth dialog, token is in the URL
    token_path = f"/{credential}"
    url = f"http://{host_ip}:{port}{token_path}/"

    # Spawn ttyd
    proc = subprocess.Popen(
        [
            TTYD_BIN,
            "--writable",
            "--once",
            "--base-path", token_path,
            "--port", str(port),
            "--interface", "0.0.0.0",
            "bash", "-c", shell_cmd,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    terminal = TerminalInfo(
        terminal_id=terminal_id,
        project_name=project_name,
        project_path=project_path,
        port=port,
        credential=credential,
        url=url,
        tmux_session=tmux_name,
        pid=proc.pid,
        started_at=datetime.utcnow().isoformat(),
        attach_mode=attach_mode,
    )
    _terminals[terminal_id] = terminal

    # Auto-kill after timeout
    asyncio.create_task(_auto_kill(terminal_id, proc.pid, timeout))

    logger.info(f"Terminal started: {terminal_id} on port {port} for {project_name}")
    return terminal


async def stop_terminal(terminal_id: str) -> bool:
    terminal = _terminals.get(terminal_id)
    if not terminal:
        return False
    try:
        os.kill(terminal.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    _terminals.pop(terminal_id, None)
    return True


def list_terminals() -> list:
    # Clean up dead terminals
    dead = [tid for tid, t in _terminals.items() if not _is_pid_alive(t.pid)]
    for tid in dead:
        del _terminals[tid]
    return [t.to_dict() for t in _terminals.values()]


def get_terminal(terminal_id: str) -> Optional[Dict]:
    t = _terminals.get(terminal_id)
    if not t or not _is_pid_alive(t.pid):
        _terminals.pop(terminal_id, None)
        return None
    return t.to_dict()
