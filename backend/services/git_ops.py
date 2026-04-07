from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List

from config import PROJECT_ROOTS


def _run_git(cwd: str, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=cwd, capture_output=True, text=True, timeout=30,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _find_git_repos() -> List[Path]:
    repos = []
    seen = set()
    for root in PROJECT_ROOTS:
        try:
            if not root.is_dir():
                continue
            for entry in root.iterdir():
                if not entry.is_dir():
                    continue
                real = entry.resolve()
                if real in seen:
                    continue
                seen.add(real)
                if (entry / ".git").exists():
                    repos.append(entry)
        except OSError:
            continue
    return sorted(repos, key=lambda p: p.name.lower())


def check_all_status() -> List[Dict]:
    results = []
    for repo in _find_git_repos():
        status = _run_git(str(repo), "status", "--porcelain")
        branch = _run_git(str(repo), "rev-parse", "--abbrev-ref", "HEAD")
        results.append({
            "name": repo.name,
            "path": str(repo),
            "branch": branch,
            "clean": status == "",
            "changes": len(status.split("\n")) if status else 0,
        })
    return results


def pull_all() -> List[Dict]:
    results = []
    for repo in _find_git_repos():
        output = _run_git(str(repo), "pull", "--ff-only")
        results.append({
            "name": repo.name,
            "result": output or "no remote or error",
        })
    return results


def prune_branches() -> List[Dict]:
    results = []
    for repo in _find_git_repos():
        _run_git(str(repo), "fetch", "--prune")
        merged = _run_git(str(repo), "branch", "--merged", "HEAD")
        pruned = []
        for branch in merged.split("\n"):
            branch = branch.strip()
            if branch and not branch.startswith("*") and branch not in ("main", "master", "develop"):
                _run_git(str(repo), "branch", "-d", branch)
                pruned.append(branch)
        results.append({
            "name": repo.name,
            "pruned": pruned,
        })
    return results
