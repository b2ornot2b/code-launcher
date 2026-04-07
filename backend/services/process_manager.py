from __future__ import annotations

import getpass
import os
import signal
import subprocess
from typing import Dict, List

import psutil

# Only allow managing launchd agents with these prefixes
ALLOWED_LAUNCHD_PREFIXES = ("com.b2.",)


def get_top_processes(limit: int = 20) -> List[Dict]:
    result = []
    current_user = getpass.getuser()
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "username"]):
        try:
            info = proc.info
            if info["username"] != current_user:
                continue
            result.append({
                "pid": info["pid"],
                "name": info["name"],
                "cpu_percent": round(info["cpu_percent"] or 0, 1),
                "memory_percent": round(info["memory_percent"] or 0, 1),
                "username": info["username"],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    result.sort(key=lambda x: x.get("cpu_percent", 0), reverse=True)
    return result[:limit]


def kill_process(pid: int) -> bool:
    """Kill a process, but only if it belongs to the current user."""
    try:
        proc = psutil.Process(pid)
        if proc.username() != getpass.getuser():
            return False
        os.kill(pid, signal.SIGTERM)
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, ProcessLookupError):
        return False


def list_launchd_agents() -> List[Dict]:
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=10,
        )
        agents = []
        for line in result.stdout.strip().split("\n")[1:]:
            parts = line.split("\t")
            if len(parts) >= 3:
                agents.append({
                    "pid": parts[0] if parts[0] != "-" else None,
                    "status": int(parts[1]) if parts[1] != "-" else None,
                    "label": parts[2],
                })
        return agents
    except Exception:
        return []


def launchd_action(label: str, action: str) -> bool:
    if action not in ("start", "stop"):
        return False
    # Only allow managing our own agents
    if not any(label.startswith(prefix) for prefix in ALLOWED_LAUNCHD_PREFIXES):
        return False
    try:
        subprocess.run(
            ["launchctl", action, label],
            capture_output=True, text=True, timeout=10,
        )
        return True
    except Exception:
        return False
