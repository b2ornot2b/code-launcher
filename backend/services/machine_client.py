"""Async HTTP client wrapping a remote CCL node's REST API."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0  # seconds for normal requests
_PROBE_TIMEOUT = 3.0  # seconds for health probes


class MachineClient:
    """Talks to one CCL backend instance over HTTP."""

    def __init__(self, machine_id: str, name: str, base_url: str, api_key: str):
        self.machine_id = machine_id
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.online = False
        self._client = httpx.AsyncClient(
            base_url=f"{self.base_url}/api/v1",
            headers={"X-API-Key": self.api_key},
            timeout=_TIMEOUT,
        )

    async def close(self):
        await self._client.aclose()

    async def _get(self, path: str, timeout: Optional[float] = None) -> Any:
        r = await self._client.get(path, timeout=timeout)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, json: Optional[Dict] = None, timeout: Optional[float] = None) -> Any:
        r = await self._client.post(path, json=json or {}, timeout=timeout)
        r.raise_for_status()
        return r.json()

    async def _delete(self, path: str, timeout: Optional[float] = None) -> Any:
        r = await self._client.delete(path, timeout=timeout)
        r.raise_for_status()
        return r.json()

    async def health(self, timeout: float = _PROBE_TIMEOUT) -> Dict:
        r = await self._client.get("/health", timeout=timeout)
        r.raise_for_status()
        return r.json()

    async def check_online(self) -> bool:
        try:
            await self.health()
            self.online = True
        except Exception:
            self.online = False
        return self.online

    # --- Projects ---

    async def list_projects(self) -> List[Dict]:
        resp = await self._get("/projects")
        return resp.get("data", [])

    async def get_project(self, slug: str) -> Optional[Dict]:
        try:
            resp = await self._get(f"/projects/{slug}")
            return resp.get("data")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    # --- Sessions ---

    async def list_sessions(self) -> List[Dict]:
        resp = await self._get("/sessions")
        return resp.get("data", [])

    async def start_session(self, project_slug: str, name: str = "", experiment: bool = False) -> Dict:
        resp = await self._post("/sessions", json={
            "project_slug": project_slug,
            "name": name,
            "experiment": experiment,
        })
        return resp.get("data", {})

    async def get_session(self, session_id: str) -> Optional[Dict]:
        try:
            resp = await self._get(f"/sessions/{session_id}")
            return resp.get("data")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def stop_session(self, session_id: str) -> bool:
        try:
            await self._delete(f"/sessions/{session_id}")
            return True
        except httpx.HTTPStatusError:
            return False

    async def respond_to_prompt(self, session_id: str, response: str) -> bool:
        try:
            await self._post(f"/sessions/{session_id}/respond", json={"response": response})
            return True
        except httpx.HTTPStatusError:
            return False

    async def trust_and_launch(self, project_path: str, project_name: str, name: str = "") -> Dict:
        resp = await self._post("/sessions/trust-and-launch", json={
            "project_path": project_path,
            "project_name": project_name,
            "name": name,
        })
        return resp.get("data", {})

    # --- Terminal ---

    async def start_terminal(self, project_slug: str) -> Dict:
        resp = await self._post("/terminal", json={"project_slug": project_slug})
        return resp.get("data", {})

    async def attach_terminal(self, session_id: str) -> Dict:
        resp = await self._post(f"/terminal/attach/{session_id}")
        return resp.get("data", {})

    async def list_terminals(self) -> List[Dict]:
        resp = await self._get("/terminal")
        return resp.get("data", [])

    async def stop_terminal(self, terminal_id: str) -> bool:
        try:
            await self._delete(f"/terminal/{terminal_id}")
            return True
        except httpx.HTTPStatusError:
            return False

    # --- System ---

    async def get_system_status(self) -> Dict:
        resp = await self._get("/system/status")
        return resp.get("data", {})

    async def get_processes(self, limit: int = 20) -> List:
        resp = await self._get(f"/system/processes?limit={limit}")
        return resp.get("data", [])

    async def kill_process(self, pid: int) -> bool:
        try:
            await self._post(f"/system/processes/{pid}/kill")
            return True
        except httpx.HTTPStatusError:
            return False

    # --- Git ---

    async def git_status(self) -> List:
        resp = await self._get("/system/git/status")
        return resp.get("data", [])

    async def git_pull_all(self) -> str:
        resp = await self._post("/system/git/pull-all")
        return resp.get("data", {}).get("job_id", "")

    async def git_prune(self) -> str:
        resp = await self._post("/system/git/prune")
        return resp.get("data", {}).get("job_id", "")

    # --- Cleanup ---

    async def run_cleanup(self, targets: List[str]) -> str:
        resp = await self._post("/system/cleanup", json={"targets": targets})
        return resp.get("data", {}).get("job_id", "")

    # --- Power ---

    async def power(self, action: str) -> Dict:
        resp = await self._post(f"/power/{action}")
        return resp.get("data", {})

    # --- Settings ---

    async def get_settings(self) -> Dict:
        resp = await self._get("/settings")
        return resp.get("data", {})

    async def update_project_root(self, action: str, path: str) -> Dict:
        resp = await self._post("/settings/project-roots", json={"action": action, "path": path})
        return resp.get("data", {})

    async def detect_dirs(self) -> List[Dict]:
        resp = await self._get("/settings/detect-dirs")
        return resp.get("data", [])

    # --- Hub Pairing (unauthenticated, one-time) ---

    async def pair_hub(self) -> Optional[Dict]:
        """Call POST /pair-hub on the node to get its API key. Returns None if already paired."""
        try:
            r = await self._client.post("/pair-hub")
            r.raise_for_status()
            return r.json().get("data")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                return None
            raise

    # --- Scaffold ---

    async def list_templates(self) -> list:
        resp = await self._get("/scaffold/templates")
        return resp.get("data", [])

    async def create_project(self, template: str, name: str) -> dict:
        resp = await self._post("/scaffold", json={"template": template, "name": name})
        return resp.get("data", {})

    # --- Background Jobs ---

    async def get_job(self, job_id: str) -> Optional[Dict]:
        try:
            resp = await self._get(f"/system/jobs/{job_id}")
            return resp.get("data")
        except httpx.HTTPStatusError:
            return None

    def to_dict(self) -> Dict:
        return {
            "id": self.machine_id,
            "name": self.name,
            "url": self.base_url,
            "online": self.online,
        }
