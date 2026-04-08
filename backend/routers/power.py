from __future__ import annotations

import logging
import subprocess

from fastapi import APIRouter, Depends, HTTPException

from auth import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/power", tags=["power"], dependencies=[Depends(require_api_key)])

ALLOWED_ACTIONS = {
    "shutdown": ["sudo", "shutdown", "-h", "now"],
    "restart": ["sudo", "shutdown", "-r", "now"],
    "sleep": ["pmset", "sleepnow"],
}


@router.post("/{action}")
async def power_action(action: str):
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid action. Allowed: {list(ALLOWED_ACTIONS.keys())}")

    cmd = ALLOWED_ACTIONS[action]
    try:
        logger.warning(f"Power action initiated: {action}")
        subprocess.Popen(cmd)
        return {"data": {"action": action, "initiated": True}}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to execute power action")
