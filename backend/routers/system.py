from __future__ import annotations

import asyncio
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_api_key
from services import system_info, process_manager, git_ops, cleanup

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(require_api_key)])

# Background job tracking (bounded)
_jobs: Dict[str, Dict] = {}
MAX_JOBS = 100


class CleanupRequest(BaseModel):
    targets: List[str]  # "brew", "pip", "logs", "trash"


class InstallRequest(BaseModel):
    package: str


# --- Status ---

@router.get("/status")
async def system_status():
    return {"data": system_info.get_system_status()}


# --- Processes ---

@router.get("/processes")
async def top_processes(limit: int = 20):
    return {"data": process_manager.get_top_processes(limit)}


@router.post("/processes/{pid}/kill")
async def kill_process(pid: int):
    if process_manager.kill_process(pid):
        return {"data": {"killed": True, "pid": pid}}
    raise HTTPException(status_code=404, detail="Process not found or access denied")


# --- LaunchD ---

@router.get("/launchd")
async def list_agents():
    return {"data": process_manager.list_launchd_agents()}


@router.post("/launchd/{label}/{action}")
async def launchd_action(label: str, action: str):
    if action not in ("start", "stop"):
        raise HTTPException(status_code=400, detail="Action must be 'start' or 'stop'")
    if process_manager.launchd_action(label, action):
        return {"data": {"label": label, "action": action, "success": True}}
    raise HTTPException(status_code=500, detail="Failed to perform action")


# --- Git ---

@router.get("/git/status")
async def git_status():
    return {"data": git_ops.check_all_status()}


@router.post("/git/pull-all")
async def git_pull_all():
    job_id = _start_background_job("pull-all", git_ops.pull_all)
    return {"data": {"job_id": job_id}}


@router.post("/git/prune")
async def git_prune():
    job_id = _start_background_job("prune", git_ops.prune_branches)
    return {"data": {"job_id": job_id}}


# --- Cleanup ---

@router.post("/cleanup")
async def run_cleanup(req: CleanupRequest):
    job_id = _start_background_job("cleanup", cleanup.run_cleanup, req.targets)
    return {"data": {"job_id": job_id}}


# --- Plugins (Homebrew) ---

@router.get("/plugins")
async def list_plugins():
    return {"data": cleanup.list_brew_packages()}


@router.post("/plugins/install")
async def install_plugin(req: InstallRequest):
    job_id = _start_background_job("install", cleanup.brew_install, req.package)
    return {"data": {"job_id": job_id}}


@router.delete("/plugins/{package}")
async def uninstall_plugin(package: str):
    result = cleanup.brew_uninstall(package)
    return {"data": {"package": package, "result": result}}


# --- Background Jobs ---

@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"data": job}


def _start_background_job(name: str, func, *args) -> str:
    # Evict completed jobs if over limit
    if len(_jobs) >= MAX_JOBS:
        done = [jid for jid, j in _jobs.items() if j["status"] in ("completed", "failed")]
        for jid in done:
            del _jobs[jid]

    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"id": job_id, "name": name, "status": "running", "result": None}

    async def run():
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, func, *args)
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["result"] = result
        except Exception as e:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["result"] = str(e)

    asyncio.create_task(run())
    return job_id
