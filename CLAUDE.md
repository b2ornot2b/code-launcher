# Claude Code Launcher

See [README.md](README.md) for full documentation.

## Quick Reference

```bash
cd backend && ./run.sh                    # Start server
curl localhost:8420/api/v1/health         # Health check
tmux attach -t ccl-<name>                 # Attach to session
sprint next                               # Execute next task (Gemma 4)
sprint run                                # Execute all tasks
```

## Project Structure
- `backend/` — FastAPI server (main.py, config.py, auth.py)
- `backend/routers/` — API endpoints (projects, sessions, system, power, scaffold, terminal, settings_api, telegram_ctrl)
- `backend/services/` — Core logic (session_manager, terminal_manager, project_scanner, machine_registry, machine_client, discovery, hub_pairing, scaffolder, session_poller, cleanup, git_ops, process_manager, settings, system_info)
- `backend/tg_bot/` — Telegram bot (bot, handlers, pairing)
- `backend/templates/` — Scaffolding templates (android, cli_python, cloud_terraform, fastapi, hybrid, website)
- `bin/sprint` — Sprint execution CLI

## Key Conventions
- Sessions in tmux: `ccl-<project>-<YYMMDDHHmmss>`
- Terminal tmux: `ccl-<project>-term-<YYMMDDHHmmss>`
- Config: `backend/.env` (secrets), `backend/settings.json` (runtime)
- Python 3.9 compat: no match statements, no `X | Y` unions, use `from __future__ import annotations`
