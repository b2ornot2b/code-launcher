# Claude Code Launcher

System management tool with three interfaces:
1. **FastAPI backend** (core) — REST API on port 8420
2. **Telegram bot** (optional, disabled by default) — pairing protocol for auth
3. **Flutter iOS app** (planned) — connects over Tailscale

## Project Structure
- `backend/` — Python FastAPI server
- `app/` — Flutter iOS app (Phase 5)

## Backend
- Entry point: `backend/main.py`
- Config: `backend/config.py` reads from `backend/.env`
- Auth: API key via `X-API-Key` header
- Routers: projects, sessions, system, power, scaffold, telegram
- Services: project_scanner, session_manager, system_info, process_manager, git_ops, cleanup, scaffolder

## Running
```bash
cd backend && ./setup_venv.sh && ./run.sh
```

## Key paths
- Projects scanned from: `/Volumes/b2/Developer/mine/`, `/Users/b2/Developer/mine/`
- Claude binary: `/Users/b2/.local/bin/claude`
- Sessions launched via: `claude remote-control --name "ProjectName"`
