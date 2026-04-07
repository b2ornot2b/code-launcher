from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_api_key
from services.project_scanner import scan_projects, get_project

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(require_api_key)])


@router.get("")
async def list_projects(search: Optional[str] = Query(None)):
    projects = scan_projects()
    if search:
        search_lower = search.lower()
        projects = [p for p in projects if search_lower in p.name.lower()]
    return {"data": [p.to_dict() for p in projects]}


@router.get("/{slug}")
async def project_detail(slug: str):
    project = get_project(slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"data": project.to_dict()}
