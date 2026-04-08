from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Dict, Set

from config import PAIRED_USERS_FILE

logger = logging.getLogger(__name__)

# Active pairing codes: {code: expiry_timestamp}
_pending_codes: Dict[str, float] = {}
# Failed attempts per user_id: {user_id: (count, first_attempt_time)}
_failed_attempts: Dict[int, tuple] = {}
CODE_TTL = 300  # 5 minutes
MAX_ATTEMPTS = 5  # per 5-minute window


def _load_paired_users() -> Set[int]:
    if PAIRED_USERS_FILE.exists():
        try:
            return set(json.loads(PAIRED_USERS_FILE.read_text()))
        except (json.JSONDecodeError, TypeError):
            pass
    return set()


def _save_paired_users(users: Set[int]) -> None:
    # Atomic write to prevent corruption
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=PAIRED_USERS_FILE.parent, suffix=".tmp", delete=False
    )
    try:
        tmp.write(json.dumps(sorted(users)))
        tmp.close()
        Path(tmp.name).replace(PAIRED_USERS_FILE)
        os.chmod(PAIRED_USERS_FILE, 0o600)
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise


def generate_pairing_code() -> str:
    """Generate an 8-character alphanumeric pairing code."""
    now = time.time()
    expired = [c for c, t in _pending_codes.items() if t < now]
    for c in expired:
        del _pending_codes[c]

    code = secrets.token_hex(4).upper()  # 8-char hex = 4 billion possibilities
    _pending_codes[code] = now + CODE_TTL
    # Code is only returned via authenticated API endpoint, not logged
    return code


def _is_rate_limited(user_id: int) -> bool:
    now = time.time()
    if user_id in _failed_attempts:
        count, first_time = _failed_attempts[user_id]
        if now - first_time > CODE_TTL:
            del _failed_attempts[user_id]
            return False
        if count >= MAX_ATTEMPTS:
            return True
    return False


def _record_failed_attempt(user_id: int) -> None:
    now = time.time()
    if user_id in _failed_attempts:
        count, first_time = _failed_attempts[user_id]
        if now - first_time > CODE_TTL:
            _failed_attempts[user_id] = (1, now)
        else:
            _failed_attempts[user_id] = (count + 1, first_time)
    else:
        _failed_attempts[user_id] = (1, now)


def verify_pairing_code(code: str, user_id: int) -> bool:
    """Verify a pairing code and add user to paired list."""
    if _is_rate_limited(user_id):
        return False

    now = time.time()
    if code in _pending_codes and _pending_codes[code] > now:
        del _pending_codes[code]
        users = _load_paired_users()
        users.add(user_id)
        _save_paired_users(users)
        logger.info(f"User {user_id} paired successfully")
        # Clear failed attempts on success
        _failed_attempts.pop(user_id, None)
        return True

    _record_failed_attempt(user_id)
    return False


def unpair_user(user_id: int) -> bool:
    users = _load_paired_users()
    if user_id in users:
        users.discard(user_id)
        _save_paired_users(users)
        return True
    return False


def is_paired(user_id: int) -> bool:
    return user_id in _load_paired_users()


def get_paired_users() -> Set[int]:
    return _load_paired_users()
