"""Tailscale-based auto-discovery of CCL nodes on the same tailnet."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import List, Tuple

import httpx

from config import PORT

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT = 3.0  # seconds


async def get_tailscale_peers() -> List[str]:
    """Get Tailscale peer IPs from `tailscale status --json`."""
    try:
        from config import TAILSCALE_BIN
        proc = await asyncio.create_subprocess_exec(
            TAILSCALE_BIN, "status", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            logger.debug(f"tailscale status failed: {stderr.decode()}")
            return []

        data = json.loads(stdout.decode())
        peers = []

        # Self node
        self_node = data.get("Self", {})
        # Don't include self — we already register as "local"

        # Peer nodes
        for peer_id, peer in data.get("Peer", {}).items():
            if not peer.get("Online", False):
                continue
            addrs = peer.get("TailscaleIPs", [])
            if addrs:
                # Prefer IPv4
                ipv4 = [a for a in addrs if "." in a]
                ip = ipv4[0] if ipv4 else addrs[0]
                peers.append(ip)

        return peers
    except FileNotFoundError:
        logger.debug("tailscale CLI not found — discovery disabled")
        return []
    except (asyncio.TimeoutError, json.JSONDecodeError, Exception) as e:
        logger.debug(f"tailscale discovery error: {e}")
        return []


async def probe_peer(ip: str, port: int = PORT) -> Tuple[str, dict]:
    """Probe a peer for a CCL health endpoint. Returns (url, health_data) or raises."""
    url = f"http://{ip}:{port}"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{url}/api/v1/health", timeout=_PROBE_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "ok":
            raise ValueError("Not a CCL instance")
        return url, data


async def discover_nodes(registry) -> List[dict]:
    """Scan Tailscale peers for CCL instances. Returns list of newly discovered nodes."""
    peers = await get_tailscale_peers()
    if not peers:
        return []

    discovered = []
    sem = asyncio.Semaphore(20)

    async def check_peer(ip):
        async with sem:
            try:
                url, health = await probe_peer(ip)
                if registry.is_known_url(url):
                    return
                if not health.get("registration_open", False):
                    return  # already paired with another hub
                name = health.get("machine_name", ip)
                mid = registry.add_pending(name, url)
                discovered.append({"id": mid, "name": name, "url": url})
            except Exception:
                pass  # not a CCL instance or unreachable

    await asyncio.gather(*[check_peer(ip) for ip in peers])

    if discovered:
        logger.info(f"Discovered {len(discovered)} new CCL node(s): {[d['name'] for d in discovered]}")

    return discovered


async def discovery_loop(registry, interval: int = 60):
    """Run discovery periodically. Call as a background task."""
    while True:
        try:
            await discover_nodes(registry)
        except Exception as e:
            logger.error(f"Discovery loop error: {e}")
        await asyncio.sleep(interval)
