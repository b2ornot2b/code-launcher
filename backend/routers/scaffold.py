from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_api_key
from services.scaffolder import list_templates, create_project

router = APIRouter(prefix="/scaffold", tags=["scaffold"], dependencies=[Depends(require_api_key)])


class CreateProjectRequest(BaseModel):
    template: str
    name: str
    base_dir: str = ""


@router.get("/templates")
async def get_templates():
    return {"data": list_templates()}


@router.post("")
async def scaffold_project(req: CreateProjectRequest):
    result = create_project(req.template, req.name, req.base_dir)
    if "error" in result:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=result["error"])
    return {"data": result}
