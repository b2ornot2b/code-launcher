from __future__ import annotations

import platform
import subprocess
from typing import Dict

import psutil


def get_system_status() -> Dict:
    disk = psutil.disk_usage("/")
    mem = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=0.5)
    boot_time = psutil.boot_time()
    uptime = psutil.time.time() - boot_time

    status = {
        "hostname": platform.node(),
        "os": f"macOS {platform.mac_ver()[0]}",
        "uptime_seconds": int(uptime),
        "cpu": {
            "percent": cpu_percent,
            "cores": psutil.cpu_count(),
        },
        "memory": {
            "total_gb": round(mem.total / (1024 ** 3), 1),
            "used_gb": round(mem.used / (1024 ** 3), 1),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / (1024 ** 3), 1),
            "used_gb": round(disk.used / (1024 ** 3), 1),
            "percent": disk.percent,
        },
        "battery": _get_battery(),
        "network": _get_network(),
    }
    return status


def _get_battery() -> Dict:
    battery = psutil.sensors_battery()
    if not battery:
        return {"available": False}
    return {
        "available": True,
        "percent": battery.percent,
        "charging": battery.power_plugged,
    }


def _get_network() -> Dict:
    addrs = psutil.net_if_addrs()
    result = {}
    for iface, addr_list in addrs.items():
        if iface.startswith("lo"):
            continue
        for addr in addr_list:
            if addr.family.name == "AF_INET":
                result[iface] = addr.address
                break
    return result
