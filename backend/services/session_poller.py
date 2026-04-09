"""Hub-side polling: detect session state changes on remote nodes and trigger notifications."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from services.machine_registry import MachineRegistry

logger = logging.getLogger(__name__)


async def poll_sessions(registry: MachineRegistry, notify_fn: Callable):
    """Poll all online machines for session state changes.

    notify_fn signature: async fn(machine_id, machine_name, session_id, project_name, prompt_text, status, project_path)
    """
    for machine in registry.list_online_machines():
        if machine.machine_id == "local":
            # Local sessions use in-memory callbacks — skip polling
            continue

        try:
            sessions = await machine.list_sessions()
        except Exception:
            machine.online = False
            continue

        prev = registry.get_session_snapshot(machine.machine_id)
        prev_by_id = {s.get("session_id"): s for s in prev}

        for session in sessions:
            sid = session.get("session_id", "")
            status = session.get("status", "")
            prev_session = prev_by_id.get(sid)

            if prev_session is None:
                # New session — no transition to report, but record it
                continue

            prev_status = prev_session.get("status", "")
            if status != prev_status and status in ("blocked", "dead"):
                try:
                    await notify_fn(
                        machine_id=machine.machine_id,
                        machine_name=machine.name,
                        session_id=sid,
                        project_name=session.get("project_name", ""),
                        prompt_text=session.get("blocked_prompt", ""),
                        status=status,
                        project_path=session.get("project_path", ""),
                    )
                except Exception as e:
                    logger.error(f"Notification error for {sid} on {machine.name}: {e}")

        registry.set_session_snapshot(machine.machine_id, sessions)


async def poller_loop(registry: MachineRegistry, notify_fn: Callable, interval: float = 5.0):
    """Run session polling periodically. Call as a background task."""
    while True:
        try:
            await poll_sessions(registry, notify_fn)
        except Exception as e:
            logger.error(f"Session poller error: {e}")
        await asyncio.sleep(interval)
