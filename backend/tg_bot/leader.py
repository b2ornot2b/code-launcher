"""File-lock based leader election for Telegram bot polling.

Uses a shared lock file so only one machine on the shared volume runs the bot.
The lock auto-releases on process exit (even on crash).
"""
from __future__ import annotations

import fcntl
import logging
import os
from typing import Optional

from config import SHARED_DIR, MACHINE_NAME

logger = logging.getLogger(__name__)

_LOCK_FILE = SHARED_DIR / ".telegram_leader.lock"
_lock_fd = None  # type: Optional[int]


def try_acquire_leadership():
    # type: () -> bool
    """Try to become the Telegram leader. Returns True if acquired.

    If SHARED_DIR doesn't exist (no shared volume), skip locking and return True.
    Telegram conflict detection serves as fallback for independent machines.
    """
    global _lock_fd
    if not SHARED_DIR.is_dir():
        logger.info(f"No shared dir, assuming leadership as '{MACHINE_NAME}'")
        return True
    fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        os.close(fd)
        logger.info("Another machine holds Telegram leadership, running as node")
        return False
    try:
        os.write(fd, MACHINE_NAME.encode())
        os.ftruncate(fd, len(MACHINE_NAME))
    except OSError:
        pass  # non-critical, lock is held regardless
    _lock_fd = fd
    logger.info(f"Acquired Telegram leadership as '{MACHINE_NAME}'")
    return True


def release_leadership():
    # type: () -> None
    """Release the lock (called on shutdown)."""
    global _lock_fd
    if _lock_fd is not None:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            os.close(_lock_fd)
        except OSError:
            pass
        _lock_fd = None
