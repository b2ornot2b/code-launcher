from __future__ import annotations

import hmac
import time
from collections import defaultdict

from fastapi import Header, HTTPException, Request

from config import API_KEY

# Rate limiting: max requests per window per IP
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 100  # requests per window
_request_counts: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(client_ip: str) -> None:
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    timestamps = _request_counts[client_ip]
    # Prune old entries
    _request_counts[client_ip] = [t for t in timestamps if t > window_start]
    if len(_request_counts[client_ip]) >= RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _request_counts[client_ip].append(now)


async def require_api_key(request: Request, x_api_key: str = Header(...)) -> str:
    _check_rate_limit(request.client.host if request.client else "unknown")
    if not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
