"""Machine registry: tracks discovered CCL nodes, manages approval and status."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from config import DATA_DIR, API_KEY, MACHINE_NAME, PORT
from services.machine_client import MachineClient

logger = logging.getLogger(__name__)

MACHINES_FILE = DATA_DIR / "machines.json"

# Singleton registry
_registry = None  # type: Optional[MachineRegistry]


class MachineRegistry:
    def __init__(self):
        self._machines = {}  # type: Dict[str, MachineClient]
        self._pending = {}  # type: Dict[str, Dict]
        self._session_snapshots = {}  # type: Dict[str, List]
        self._on_discovered = None  # type: Optional[Callable]

    def set_discovery_callback(self, fn):
        # type: (Callable) -> None
        """Set callback for when new machines are discovered. fn(machine_id, name, url)"""
        self._on_discovered = fn

    # --- Persistence ---

    def load(self):
        """Load machines from machines.json."""
        if MACHINES_FILE.exists():
            try:
                data = json.loads(MACHINES_FILE.read_text())
                for m in data.get("machines", []):
                    mid = m["id"]
                    self._machines[mid] = MachineClient(
                        machine_id=mid,
                        name=m["name"],
                        base_url=m["url"],
                        api_key=m.get("api_key", ""),
                    )
                logger.info(f"Loaded {len(self._machines)} machine(s) from {MACHINES_FILE}")
            except (json.JSONDecodeError, OSError, KeyError) as e:
                logger.warning(f"Could not load machines.json: {e}")

    def save(self):
        """Write machines to machines.json atomically."""
        data = {
            "machines": [
                {
                    "id": m.machine_id,
                    "name": m.name,
                    "url": m.base_url,
                    "api_key": m.api_key,
                    "is_hub": m.machine_id == "local",
                }
                for m in self._machines.values()
            ]
        }
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
            with open(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.chmod(tmp, 0o600)
            Path(tmp).replace(MACHINES_FILE)
            tmp = None  # successfully replaced, don't clean up
        except OSError as e:
            logger.error(f"Failed to save machines.json: {e}")
        finally:
            if tmp:
                try:
                    Path(tmp).unlink(missing_ok=True)
                except OSError:
                    pass

    # --- Self-registration (hub registers itself) ---

    def ensure_self_registered(self):
        """Register or update the local machine entry."""
        local = self._machines.get("local")
        if local is None:
            self._machines["local"] = MachineClient(
                machine_id="local",
                name=MACHINE_NAME,
                base_url=f"http://localhost:{PORT}",
                api_key=API_KEY,
            )
            self._machines["local"].online = True
            self.save()
            logger.info(f"Self-registered as '{MACHINE_NAME}' (local)")
        elif local.name != MACHINE_NAME or local.api_key != API_KEY:
            local.name = MACHINE_NAME
            local.api_key = API_KEY
            local.base_url = f"http://localhost:{PORT}"
            local.online = True
            self.save()
            logger.info(f"Updated local machine to '{MACHINE_NAME}'")
        else:
            local.online = True

    def update_local_url(self, url):
        # type: (str) -> None
        """Update the local machine's URL (e.g. with Tailscale IP)."""
        local = self._machines.get("local")
        if local and local.base_url != url:
            local.base_url = url
            self.save()
            logger.info(f"Updated local URL to {url}")

    # --- Discovery / Registration ---

    def is_known_url(self, url: str) -> bool:
        """Check if a URL is already registered or pending."""
        for m in self._machines.values():
            if m.base_url == url:
                return True
        for p in self._pending.values():
            if p.get("url") == url:
                return True
        return False

    def _generate_id(self, name):
        # type: (str) -> str
        """Generate a unique machine ID from a name."""
        base_id = name.lower().replace(" ", "-").replace(".", "-")
        mid = base_id
        counter = 2
        while mid in self._machines or mid in self._pending:
            mid = f"{base_id}-{counter}"
            counter += 1
        return mid

    async def _pair_and_register(self, mid, name, url):
        # type: (str, str, str) -> Optional[MachineClient]
        """Call pair-hub on a remote node and register it."""
        temp = MachineClient(mid, name, url, "")
        result = await temp.pair_hub()
        if not result:
            return None
        client = MachineClient(
            machine_id=mid,
            name=result.get("machine_name", name),
            base_url=url,
            api_key=result["api_key"],
        )
        client.online = True
        self._machines[mid] = client
        self.save()
        return client

    def add_pending(self, name: str, url: str) -> str:
        """Add a discovered node as pending approval. Returns machine_id."""
        mid = self._generate_id(name)
        self._pending[mid] = {"name": name, "url": url}
        logger.info(f"New machine pending approval: {name} ({url}) as {mid}")

        if self._on_discovered:
            try:
                self._on_discovered(mid, name, url)
            except Exception as e:
                logger.error(f"Discovery callback error: {e}")

        return mid

    async def approve(self, machine_id: str) -> Optional[MachineClient]:
        """Approve a pending machine: call pair-hub to get API key, activate it."""
        info = self._pending.pop(machine_id, None)
        if not info:
            return None
        client = await self._pair_and_register(machine_id, info["name"], info["url"])
        if not client:
            logger.warning(f"pair-hub failed for {machine_id} — may already be paired")
            return None
        logger.info(f"Machine approved: {client.name} ({machine_id})")
        return client

    async def auto_approve(self, name: str, url: str) -> Optional[MachineClient]:
        """Auto-approve a trusted machine (shared codebase). Skips pending queue."""
        if self.is_known_url(url):
            return None
        mid = self._generate_id(name)
        client = await self._pair_and_register(mid, name, url)
        if not client:
            logger.warning(f"auto-approve pair-hub failed for {name} ({url})")
            return None
        logger.info(f"Auto-approved trusted machine: {client.name} ({mid})")
        return client

    def reject(self, machine_id: str) -> bool:
        """Reject a pending machine."""
        if machine_id in self._pending:
            del self._pending[machine_id]
            logger.info(f"Machine rejected: {machine_id}")
            return True
        return False

    async def remove(self, machine_id: str) -> bool:
        """Remove an active machine."""
        if machine_id in self._machines and machine_id != "local":
            client = self._machines.pop(machine_id)
            await client.close()
            self._session_snapshots.pop(machine_id, None)
            self.save()
            logger.info(f"Machine removed: {machine_id}")
            return True
        return False

    # --- Lookup ---

    def get_machine(self, machine_id: str) -> Optional[MachineClient]:
        return self._machines.get(machine_id)

    def list_machines(self) -> List[MachineClient]:
        return list(self._machines.values())

    def list_online_machines(self) -> List[MachineClient]:
        return [m for m in self._machines.values() if m.online]

    def list_pending(self) -> List[Dict]:
        return [
            {"id": mid, "name": info["name"], "url": info["url"]}
            for mid, info in self._pending.items()
        ]

    # --- Status ---

    async def refresh_status(self):
        """Ping all machines concurrently to update online/offline status."""
        import asyncio
        remotes = [m for m in self._machines.values() if m.machine_id != "local"]
        for m in self._machines.values():
            if m.machine_id == "local":
                m.online = True
        if remotes:
            await asyncio.gather(*[m.check_online() for m in remotes])

    # --- Session Snapshots (for polling change detection) ---

    def get_session_snapshot(self, machine_id: str) -> List[Dict]:
        return self._session_snapshots.get(machine_id, [])

    def set_session_snapshot(self, machine_id: str, sessions: List[Dict]):
        self._session_snapshots[machine_id] = sessions


def get_registry() -> MachineRegistry:
    """Get the singleton registry. Creates and loads if needed."""
    global _registry
    if _registry is None:
        _registry = MachineRegistry()
        _registry.load()
        _registry.ensure_self_registered()
    return _registry


init_registry = get_registry  # alias for clarity at startup
