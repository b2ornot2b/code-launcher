"""Node-side hub pairing: one-time API key exchange for Tailscale discovery."""
from __future__ import annotations

import fcntl
import logging
import os
from pathlib import Path

from config import DATA_DIR, API_KEY, MACHINE_NAME

logger = logging.getLogger(__name__)

_PAIRED_FLAG = DATA_DIR / ".hub_paired"
_lock_path = DATA_DIR / ".hub_paired.lock"


def is_paired() -> bool:
    return _PAIRED_FLAG.exists()


def pair_hub():
    """Called once by the hub during registration. Returns API key, then locks.

    Uses file locking to prevent race conditions where two concurrent
    requests could both succeed.
    """
    # Fast path: already paired
    if _PAIRED_FLAG.exists():
        return None

    # Acquire exclusive lock to prevent race condition
    lock_fd = os.open(str(_lock_path), os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        os.close(lock_fd)
        return None  # another request is pairing right now

    try:
        # Re-check after acquiring lock
        if _PAIRED_FLAG.exists():
            return None

        # Write the flag file — if this fails, pairing fails
        _PAIRED_FLAG.write_text("paired")
        os.chmod(str(_PAIRED_FLAG), 0o600)
        logger.info(f"Hub paired with this node ({MACHINE_NAME})")
        return {"api_key": API_KEY, "machine_name": MACHINE_NAME}
    except OSError as e:
        logger.error(f"Pairing failed — could not write flag file: {e}")
        return None
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def unpair_hub() -> None:
    """Reset pairing (for re-registration)."""
    try:
        _PAIRED_FLAG.unlink(missing_ok=True)
        _lock_path.unlink(missing_ok=True)
    except OSError:
        pass
    logger.info("Hub pairing reset")
