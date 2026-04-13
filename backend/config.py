from __future__ import annotations

import logging
import os
import socket
from pathlib import Path
from typing import List

from dotenv import load_dotenv

_base = Path(__file__).parent
load_dotenv(_base / ".env")
# Per-machine override: .env.<hostname> takes precedence
_hostname = socket.gethostname()
_host_env = _base / f".env.{_hostname}"
if _host_env.exists():
    load_dotenv(_host_env, override=True)

_logger = logging.getLogger(__name__)

# API
API_KEY: str = os.environ.get("API_KEY", "")
if not API_KEY or API_KEY == "changeme":
    raise RuntimeError("API_KEY must be set in .env (not 'changeme'). Run setup_venv.sh to generate one.")
HOST: str = os.environ.get("HOST", "0.0.0.0")
PORT: int = int(os.environ.get("PORT", "8420"))

# Telegram
TELEGRAM_ENABLED: bool = os.environ.get("TELEGRAM_ENABLED", "false").lower() == "true"
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# Machine identity
MACHINE_NAME: str = os.environ.get("MACHINE_NAME", _hostname)
IS_HUB: bool = False  # set at runtime by leader election

# Tailscale CLI path (macOS App Store uses the long path)
_TAILSCALE_PATHS = [
    "tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    "/usr/bin/tailscale",
    "/usr/local/bin/tailscale",
]

def _find_tailscale() -> str:
    import shutil
    for p in _TAILSCALE_PATHS:
        if shutil.which(p):
            return p
    return "tailscale"

TAILSCALE_BIN: str = os.environ.get("TAILSCALE_BIN", _find_tailscale())

# Paths
_default_roots = str(Path.home() / "Developer" / "mine")
PROJECT_ROOTS: List[Path] = [
    Path(p.strip())
    for p in os.environ.get("PROJECT_ROOTS", _default_roots).split(",")
]
CLAUDE_BIN: str = os.environ.get("CLAUDE_BIN", str(Path.home() / ".local" / "bin" / "claude"))

# Project detection markers
PROJECT_MARKERS = [
    ".git", "CLAUDE.md", "package.json", "pyproject.toml",
    "build.gradle.kts", "Cargo.toml", "go.mod", "Makefile",
    "pubspec.yaml", "CMakeLists.txt",
]

# Runtime dirs
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"

# Per-machine state (each machine has its own home dir)
DATA_DIR = Path.home() / ".config" / "code-launcher"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Shared state for co-located machines (optional, on shared volume)
SHARED_DIR = BASE_DIR / ".shared"

SESSIONS_DIR = DATA_DIR / "sessions"
LOGS_DIR = DATA_DIR / "logs"
PAIRED_USERS_FILE = DATA_DIR / "paired_users.json"

SESSIONS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


def set_hub_status(value):
    # type: (bool) -> None
    global IS_HUB
    IS_HUB = value


# --- One-time migration of legacy state files ---
def _migrate_legacy_files():
    import shutil
    _files = ["paired_users.json", "machines.json", "settings.json"]
    # Try both old locations: backend/<file> and backend/data/<hostname>/<file>
    _old_dirs = [
        BASE_DIR,
        BASE_DIR / "data" / MACHINE_NAME,
    ]
    for name in _files:
        new_path = DATA_DIR / name
        if new_path.exists():
            continue
        for old_dir in _old_dirs:
            old_path = old_dir / name
            if old_path.exists():
                shutil.copy2(str(old_path), str(new_path))
                _logger.info(f"Migrated {old_path} -> {new_path}")
                break

_migrate_legacy_files()
