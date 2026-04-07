from __future__ import annotations

from fastapi import APIRouter, Depends

from auth import require_api_key
from telegram.pairing import generate_pairing_code, get_paired_users
import config

router = APIRouter(prefix="/telegram", tags=["telegram"], dependencies=[Depends(require_api_key)])


@router.get("/status")
async def telegram_status():
    return {"data": {
        "enabled": config.TELEGRAM_ENABLED,
        "paired_users": sorted(get_paired_users()),
    }}


@router.post("/pair-code")
async def new_pairing_code():
    code = generate_pairing_code()
    return {"data": {"code": code, "ttl_seconds": 300}}
