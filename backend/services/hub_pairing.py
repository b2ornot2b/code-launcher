"""Node-side hub pairing: one-time API key exchange for Tailscale discovery."""
from __future__ import annotations

import logging
from pathlib import Path

from config import BASE_DIR, API_KEY, MACHINE_NAME

logger = logging.getLogger(__name__)

_PAIRED_FLAG = BASE_DIR / ".hub_paired"
_is_paired: bool = _PAIRED_FLAG.exists()


def is_paired() -> bool:
    return _is_paired


def pair_hub():
    """Called once by the hub during registration. Returns API key, then locks."""
    global _is_paired
    if _is_paired:
        return None  # already paired
    _is_paired = True
    try:
        _PAIRED_FLAG.write_text("paired")
    except OSError as e:
        logger.warning(f"Could not write paired flag: {e}")
    logger.info(f"Hub paired with this node ({MACHINE_NAME})")
    return {"api_key": API_KEY, "machine_name": MACHINE_NAME}


def unpair_hub() -> None:
    """Reset pairing (for re-registration)."""
    global _is_paired
    _is_paired = False
    try:
        _PAIRED_FLAG.unlink(missing_ok=True)
    except OSError:
        pass
    logger.info("Hub pairing reset")
