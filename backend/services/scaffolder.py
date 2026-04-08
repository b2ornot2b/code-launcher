from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path
from typing import Dict, List

from config import TEMPLATES_DIR, PROJECT_ROOTS

TEMPLATES = {
    "android": {"name": "Android App (Kotlin)", "description": "Kotlin/Gradle Android project"},
    "cli_python": {"name": "CLI Tool (Python)", "description": "Python CLI with pyproject.toml"},
    "website": {"name": "Website", "description": "Static HTML/CSS/JS site"},
    "cloud_terraform": {"name": "Cloud (Terraform)", "description": "Terraform + Python cloud project"},
    "hybrid": {"name": "Hybrid Cloud+Mobile", "description": "Combined cloud backend + mobile frontend"},
    "fastapi": {"name": "API Service (FastAPI)", "description": "FastAPI REST API service"},
}


def list_templates() -> List[Dict]:
    return [
        {"key": k, "name": v["name"], "description": v["description"]}
        for k, v in TEMPLATES.items()
    ]


def create_project(template_key: str, name: str, base_dir: str = "") -> Dict:
    if template_key not in TEMPLATES:
        return {"error": f"Unknown template: {template_key}"}

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        return {"error": "Invalid project name"}

    if base_dir:
        target_root = Path(base_dir).resolve()
        # Validate base_dir is within allowed project roots
        if not any(str(target_root).startswith(str(r.resolve())) for r in PROJECT_ROOTS):
            return {"error": f"base_dir must be within a configured project root"}
    else:
        target_root = PROJECT_ROOTS[0]
    target = target_root / slug

    if target.exists():
        return {"error": f"Directory already exists: {target}"}

    template_dir = TEMPLATES_DIR / template_key
    if template_dir.is_dir():
        shutil.copytree(template_dir, target)
    else:
        target.mkdir(parents=True)

    # Variable substitution in all text files
    substitutions = {
        "{{PROJECT_NAME}}": name,
        "{{PROJECT_SLUG}}": slug,
        "{{DATE}}": date.today().isoformat(),
    }
    for f in target.rglob("*"):
        if f.is_file():
            try:
                content = f.read_text()
                changed = False
                for placeholder, value in substitutions.items():
                    if placeholder in content:
                        content = content.replace(placeholder, value)
                        changed = True
                if changed:
                    f.write_text(content)
            except (UnicodeDecodeError, OSError):
                continue

    # Ensure CLAUDE.md exists
    claude_md = target / "CLAUDE.md"
    if not claude_md.exists():
        template_info = TEMPLATES[template_key]
        claude_md.write_text(
            f"# {name}\n\n"
            f"Type: {template_info['name']}\n"
            f"Created: {date.today().isoformat()}\n"
        )

    # Initialize Task Master with local Gemma 4 config
    _init_taskmaster(target)

    return {
        "name": name,
        "slug": slug,
        "path": str(target),
        "template": template_key,
    }


TASKMASTER_CONFIG = """{
  "models": {
    "main": {
      "provider": "openai",
      "modelId": "gemma-4-31b-it-8bit",
      "maxTokens": 8192,
      "temperature": 0.2,
      "baseURL": "http://b2studio.local:8000/v1"
    },
    "research": {
      "provider": "openai",
      "modelId": "gemma-4-31b-it-8bit",
      "maxTokens": 8192,
      "temperature": 0.1,
      "baseURL": "http://b2studio.local:8000/v1"
    },
    "fallback": {
      "provider": "openai",
      "modelId": "Qwen3.5-27B-Claude-4.6-Opus-Distilled-MLX-4bit",
      "maxTokens": 8192,
      "temperature": 0.2,
      "baseURL": "http://b2studio.local:8000/v1"
    }
  },
  "global": {
    "logLevel": "info",
    "debug": false,
    "defaultNumTasks": 10,
    "defaultSubtasks": 3,
    "defaultPriority": "medium",
    "responseLanguage": "English",
    "anonymousTelemetry": false
  }
}"""


def _init_taskmaster(project_path: Path) -> None:
    """Initialize Task Master with local Gemma 4 config in a new project."""
    tm_dir = project_path / ".taskmaster"
    tm_dir.mkdir(exist_ok=True)
    (tm_dir / "tasks").mkdir(exist_ok=True)
    (tm_dir / "docs").mkdir(exist_ok=True)

    config = tm_dir / "config.json"
    config.write_text(TASKMASTER_CONFIG)

    # .env with API key for the local LLM
    env_file = project_path / ".env"
    if not env_file.exists():
        env_file.write_text("OPENAI_API_KEY=123qwe123\n")
