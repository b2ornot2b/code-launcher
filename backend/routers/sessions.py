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
    experiment: bool = False


class RespondRequest(BaseModel):
    response: str  # e.g. "y", "n", "yes", "no"


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
        experiment=req.experiment,
    )
    return {"data": session.to_dict()}


@router.get("/{session_id}")
async def get_session(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"data": session}


@router.post("/{session_id}/respond")
async def respond_to_prompt(session_id: str, req: RespondRequest):
    success = await session_manager.respond_to_prompt(session_id, req.response)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found or not blocked")
    return {"data": {"responded": True}}


@router.delete("/{session_id}")
async def stop_session(session_id: str):
    stopped = await session_manager.stop_session(session_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"data": {"stopped": True}}


class TrustAndLaunchRequest(BaseModel):
    project_path: str
    project_name: str
    name: str = ""


@router.post("/trust-and-launch", status_code=201)
async def trust_and_launch(req: TrustAndLaunchRequest):
    session = await session_manager.trust_and_launch(
        project_path=req.project_path,
        project_name=req.project_name,
        name=req.name or None,
    )
    return {"data": session.to_dict()}
