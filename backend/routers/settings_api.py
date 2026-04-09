from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_api_key
from services import settings

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_api_key)])


class ProjectRootsRequest(BaseModel):
    action: str  # "add" or "remove"
    path: str


@router.get("")
async def get_settings():
    return {"data": settings.get_system_summary()}


@router.post("/project-roots")
async def update_project_roots(req: ProjectRootsRequest):
    if req.action == "add":
        ok = settings.add_project_root(req.path)
    elif req.action == "remove":
        ok = settings.remove_project_root(req.path)
    else:
        return {"data": {"success": False, "error": "action must be 'add' or 'remove'"}}
    return {"data": {"success": ok, "project_roots": settings.get_project_roots()}}


@router.get("/detect-dirs")
async def detect_dirs():
    return {"data": settings.detect_dev_directories()}
