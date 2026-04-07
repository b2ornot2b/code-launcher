from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_api_key
from services.project_scanner import get_project
from services import session_manager

router = APIRouter(prefix="/sessions", tags=["sessions"], dependencies=[Depends(require_api_key)])


class StartSessionRequest(BaseModel):
    project_slug: str
    name: str = ""


@router.get("")
async def list_sessions():
    return {"data": session_manager.list_sessions()}


@router.post("", status_code=201)
async def start_session(req: StartSessionRequest):
    project = get_project(req.project_slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    session = await session_manager.start_session(
        project_path=project.path,
        project_name=project.name,
        name=req.name or None,
    )
    return {"data": session.to_dict()}


@router.get("/{session_id}")
async def get_session(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"data": session}


@router.delete("/{session_id}")
async def stop_session(session_id: str):
    stopped = await session_manager.stop_session(session_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"data": {"stopped": True}}
