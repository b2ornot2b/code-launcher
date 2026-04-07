from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List

# Strict validation for brew package names
_BREW_PACKAGE_RE = re.compile(r"^[a-z0-9@._+-]+$")

VALID_CLEANUP_TARGETS = {"brew", "pip", "logs", "trash"}


def _validate_package_name(package: str) -> None:
    if not _BREW_PACKAGE_RE.match(package) or ".." in package or "/" in package:
        raise ValueError(f"Invalid package name: {package}")


def run_cleanup(targets: List[str]) -> Dict:
    results = {}
    for target in targets:
        if target not in VALID_CLEANUP_TARGETS:
            continue
        if target == "brew":
            results["brew"] = _run_cmd("brew", "cleanup", "--prune=30")
        elif target == "pip":
            results["pip"] = _run_cmd("pip3", "cache", "purge")
        elif target == "logs":
            results["logs"] = _cleanup_logs()
        elif target == "trash":
            results["trash"] = _empty_trash()
    return results


def _run_cmd(*args: str) -> str:
    try:
        result = subprocess.run(
            list(args),
            capture_output=True, text=True, timeout=120,
        )
        return result.stdout.strip() or result.stderr.strip() or "done"
    except Exception:
        return "error: command failed"


def _cleanup_logs() -> str:
    # Only clean application-specific log dirs, not shared /tmp
    log_dirs = [
        Path.home() / "Library" / "Logs",
    ]
    removed = 0
    cutoff = time.time() - (7 * 86400)
    for log_dir in log_dirs:
        try:
            for f in log_dir.glob("*.log"):
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
        except OSError:
            continue
    return f"removed {removed} old log files"


def _empty_trash() -> str:
    trash = Path.home() / ".Trash"
    removed = 0
    try:
        for item in trash.iterdir():
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink()
            removed += 1
    except OSError:
        pass
    return f"removed {removed} items from trash"


def list_brew_packages() -> List[str]:
    try:
        result = subprocess.run(
            ["brew", "list", "--formula"],
            capture_output=True, text=True, timeout=30,
        )
        return [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
    except Exception:
        return []


def brew_install(package: str) -> str:
    _validate_package_name(package)
    return _run_cmd("brew", "install", package)


def brew_uninstall(package: str) -> str:
    _validate_package_name(package)
    return _run_cmd("brew", "uninstall", package)
