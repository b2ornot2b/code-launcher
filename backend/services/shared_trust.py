"""Auto-trust machines that share the codebase directory.

A trust token is stored in the shared data/ directory. Any machine that can
read this file has filesystem access and is implicitly trusted.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from typing import Optional

from config import SHARED_DIR

_TRUST_FILE = SHARED_DIR / ".shared_trust_token"
_cached_hash = None  # type: Optional[str]


def get_or_create_trust_token():
    # type: () -> Optional[str]
    """Get the shared trust token, creating it if needed.

    Returns None if SHARED_DIR doesn't exist (no shared volume).
    """
    if not SHARED_DIR.is_dir():
        return None
    try:
        return _TRUST_FILE.read_text().strip()
    except FileNotFoundError:
        pass
    token = secrets.token_hex(16)
    try:
        fd = os.open(str(_TRUST_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, token.encode())
        finally:
            os.close(fd)
        return token
    except FileExistsError:
        return _TRUST_FILE.read_text().strip()


def get_trust_token_hash():
    # type: () -> Optional[str]
    """SHA256 hash of the trust token. Returns None if no shared volume."""
    global _cached_hash
    if _cached_hash is None:
        token = get_or_create_trust_token()
        if token is None:
            return None
        _cached_hash = hashlib.sha256(token.encode()).hexdigest()
    return _cached_hash
