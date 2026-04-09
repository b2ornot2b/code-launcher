from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


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
MACHINE_NAME: str = os.environ.get("MACHINE_NAME", socket.gethostname())
IS_HUB: bool = TELEGRAM_ENABLED  # The machine running the bot is the hub

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
SESSIONS_DIR = BASE_DIR / "sessions"
LOGS_DIR = BASE_DIR / "logs"
TEMPLATES_DIR = BASE_DIR / "templates"
PAIRED_USERS_FILE = BASE_DIR / "paired_users.json"

SESSIONS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
