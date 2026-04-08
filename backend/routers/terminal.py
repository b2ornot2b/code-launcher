from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_api_key
from services.project_scanner import get_project
from services import terminal_manager

router = APIRouter(prefix="/terminal", tags=["terminal"], dependencies=[Depends(require_api_key)])


class StartTerminalRequest(BaseModel):
    project_slug: str


@router.post("", status_code=201)
async def start_terminal(req: StartTerminalRequest):
    project = get_project(req.project_slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    terminal = await terminal_manager.start_terminal(project.path, project.name)
    return {"data": terminal.to_dict()}


@router.post("/attach/{session_id}", status_code=201)
async def attach_terminal(session_id: str):
    from services.session_manager import get_session, _sessions
    session = _sessions.get(session_id)
    if not session or not session.tmux_session:
        raise HTTPException(status_code=404, detail="Session not found")
    terminal = await terminal_manager.start_terminal(
        session.project_path, session.project_name,
        tmux_session=session.tmux_session,
    )
    return {"data": terminal.to_dict()}


@router.get("")
async def list_terminals():
    return {"data": terminal_manager.list_terminals()}


@router.delete("/{terminal_id}")
async def stop_terminal(terminal_id: str):
    stopped = await terminal_manager.stop_terminal(terminal_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Terminal not found")
    return {"data": {"stopped": True}}
