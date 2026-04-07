from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from config import PROJECT_MARKERS, PROJECT_ROOTS

CACHE_TTL = 60  # seconds


@dataclass
class ProjectInfo:
    name: str
    slug: str
    path: str
    markers: List[str] = field(default_factory=list)
    has_claude_md: bool = False

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "slug": self.slug,
            "path": self.path,
            "markers": self.markers,
            "has_claude_md": self.has_claude_md,
        }


_cache: List[ProjectInfo] = []
_cache_time: float = 0


def scan_projects(force: bool = False) -> List[ProjectInfo]:
    global _cache, _cache_time

    if not force and _cache and (time.time() - _cache_time) < CACHE_TTL:
        return _cache

    projects: List[ProjectInfo] = []
    seen_paths: set = set()

    for root in PROJECT_ROOTS:
        try:
            if not root.is_dir():
                continue
            for entry in sorted(root.iterdir()):
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                real_path = str(entry.resolve())
                if real_path in seen_paths:
                    continue
                seen_paths.add(real_path)

                markers = [m for m in PROJECT_MARKERS if (entry / m).exists()]
                if not markers:
                    continue

                projects.append(ProjectInfo(
                    name=entry.name,
                    slug=entry.name.lower().replace(" ", "-"),
                    path=str(entry),
                    markers=markers,
                    has_claude_md=(entry / "CLAUDE.md").exists(),
                ))
        except OSError:
            continue

    projects.sort(key=lambda p: p.name.lower())
    _cache = projects
    _cache_time = time.time()
    return projects


def get_project(slug: str) -> Optional[ProjectInfo]:
    for p in scan_projects():
        if p.slug == slug:
            return p
    return None
