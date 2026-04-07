from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from config import API_KEY


async def require_api_key(x_api_key: str = Header(...)) -> str:
    if not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
