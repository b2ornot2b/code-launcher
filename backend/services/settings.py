from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List

from config import DATA_DIR, CLAUDE_BIN

logger = logging.getLogger(__name__)

SETTINGS_FILE = DATA_DIR / "settings.json"

# Common developer directories to auto-detect
COMMON_DEV_DIRS = [
    Path.home() / "Developer",
    Path.home() / "Developer" / "mine",
    Path.home() / "Projects",
    Path.home() / "code",
    Path.home() / "src",
]

# Also check mounted volumes for Developer directories
def _discover_volume_dev_dirs() -> list:
    """Find Developer directories on mounted volumes."""
    found = []
    volumes = Path("/Volumes")
    if volumes.is_dir():
        try:
            for vol in volumes.iterdir():
                if vol.is_symlink() or not vol.is_dir():
                    continue
                for sub in ["Developer", "Developer/mine", "Projects"]:
                    candidate = vol / sub
                    if candidate.is_dir():
                        found.append(candidate)
        except OSError:
            pass
    return found

_settings: Dict = {}


def _load() -> Dict:
    global _settings
    if SETTINGS_FILE.exists():
        try:
            _settings = json.loads(SETTINGS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            _settings = {}
    return _settings


def _save() -> None:
    SETTINGS_FILE.write_text(json.dumps(_settings, indent=2))


def get_project_roots() -> List[str]:
    s = _load()
    return s.get("project_roots", [])


def set_project_roots(roots: List[str]) -> None:
    _load()
    _settings["project_roots"] = roots
    _save()


def add_project_root(path: str) -> bool:
    roots = get_project_roots()
    if path not in roots and Path(path).is_dir():
        roots.append(path)
        set_project_roots(roots)
        return True
    return False


def remove_project_root(path: str) -> bool:
    roots = get_project_roots()
    if path in roots:
        roots.remove(path)
        set_project_roots(roots)
        return True
    return False


def is_configured() -> bool:
    return len(get_project_roots()) > 0


def detect_dev_directories() -> List[Dict]:
    """Find common dev directories that exist on this system."""
    all_dirs = list(COMMON_DEV_DIRS) + _discover_volume_dev_dirs()
    seen = set()
    found = []
    for d in all_dirs:
        resolved = str(d.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        if d.is_dir():
            try:
                count = sum(1 for e in d.iterdir() if e.is_dir() and not e.name.startswith("."))
            except OSError:
                count = 0
            found.append({"path": str(d), "project_count": count})
    return found


def check_claude_cli() -> Dict:
    """Verify Claude CLI is installed and get version."""
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip() or result.stderr.strip()
            return {"installed": True, "path": CLAUDE_BIN, "version": version}
    except Exception:
        pass
    return {"installed": False, "path": CLAUDE_BIN, "version": None}


def get_system_summary() -> Dict:
    """Quick system check for onboarding."""
    roots = get_project_roots()
    claude = check_claude_cli()
    project_count = 0
    for root in roots:
        try:
            project_count += sum(
                1 for e in Path(root).iterdir()
                if e.is_dir() and not e.name.startswith(".")
            )
        except OSError:
            pass
    return {
        "configured": is_configured(),
        "project_roots": roots,
        "project_count": project_count,
        "claude": claude,
    }
