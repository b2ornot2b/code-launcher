# Claude Code Launcher

System management tool for launching and managing Claude Code remote-control sessions from your phone.

## Architecture
```
Telegram Bot ──> FastAPI (Mac:8420) ──> claude remote-control (tmux)
                                    ──> system management
```

## Interfaces
1. **FastAPI backend** (core) — REST API on port 8420
2. **Telegram bot** (optional) — pairing protocol, inline keyboard UI
3. **Flutter iOS app** (planned) — connects over Tailscale

## Project Structure
- `backend/` — Python FastAPI server
- `backend/tg_bot/` — Telegram bot (handlers, pairing, notifications)
- `backend/services/` — Core services (sessions, projects, system, scaffold)
- `backend/templates/` — Scaffolding templates (android, cli, web, cloud, etc.)
- `bin/sprint` — Sprint workflow CLI
- `app/` — Flutter iOS app (Phase 5)

## Running
```bash
cd backend && ./setup_venv.sh && ./run.sh
```

## Sessions
- Spawned in named tmux sessions: `ccl-<project>-<YYMMDDHHmmss>`
- Attach via SSH: `tmux attach -t ccl-<name>`
- PTY monitoring detects trust/permission prompts → Telegram notifications
- Trust & Retry: auto-accepts workspace trust dialog

## Development Workflow

```bash
sprint plan      # Write PRD, parse into tasks (Gemma 4)
sprint status    # View task dashboard
sprint next      # Execute next task (Gemma 4 via OpenCode)
sprint run       # Execute all tasks autonomously
sprint review    # Launch Claude Code to review changes
```

## Key Config
- Backend config: `backend/.env`
- Task Master: `.taskmaster/config.json` (Gemma 4 at b2studio.local:8000)
- OpenCode: `~/.config/opencode/opencode.json`
- Sprint script: `bin/sprint` (symlinked to ~/bin/sprint)
