# Claude Code Launcher

Launch and manage Claude Code remote-control sessions from your phone. Create projects, start coding sessions, monitor your system, and get a browser-based terminal — all from Telegram. Manage multiple machines over Tailscale and delegate development sprints to a local LLM while you review from the Claude Code mobile app.

## Architecture

```
Phone (Telegram)
  |
  v
FastAPI Backend — Hub (Mac:8420)
  |
  +---> claude remote-control (tmux sessions)
  +---> system management (processes, git, cleanup)
  +---> ttyd web terminals
  +---> project scaffolding
  +---> Tailscale auto-discovery (remote nodes)
  |
  +---> Claude Code Mobile App (review & plan)
  +---> OpenCode + Gemma 4 (execute tasks)
  +---> SSH: tmux attach (direct access)
```

## Features

### Session Management
- Launch Claude Code remote-control sessions from Telegram
- Sessions run in named tmux sessions (`ccl-<project>-<timestamp>`)
- Attach via SSH: `tmux attach -t ccl-<name>`
- Auto-detect workspace trust prompts — approve from Telegram
- Trust & Launch mode — auto-trust workspace before session start
- Experiment mode (git worktree isolation) for safe exploration
- Auto-cleanup of stale/dead tmux sessions
- Session recovery on server restart

### Web Terminal
- One-tap browser shell for any project from Telegram
- Token-in-URL authentication — no login dialog
- Single-use, auto-expires after 30 minutes or disconnect
- Attach to running Claude Code sessions to watch live
- Prefers Tailscale IP, falls back to LAN IP

### Multi-Machine Management
- Auto-discover other machines running CCL via Tailscale
- Approve/deny discovered nodes from Telegram
- Browse projects and sessions across all machines
- Start and manage remote sessions from a single bot
- Real-time polling detects remote session state changes (5s interval)
- Hub pairing protocol — one-time key exchange, file-locked

### Project Management
- Browse and search projects across configured directories
- Auto-detect project type via markers (.git, package.json, pyproject.toml, build.gradle.kts, Cargo.toml, go.mod, Makefile, pubspec.yaml, CMakeLists.txt)
- Create new projects from 6 templates (Android, Python CLI, Website, Cloud, Hybrid, FastAPI)
- Projects auto-initialized with Task Master + local LLM config

### Sprint Workflow
- Plan sprints with Opus (Claude Code) using Task Master MCP tools
- Execute tasks autonomously with local Gemma 4 via OpenCode
- `sprint next` / `sprint run` for hands-off execution

### System Maintenance
- System status (CPU, RAM, disk, battery, network)
- Process management (list, kill)
- Git operations (status all repos, pull all, prune branches)
- Cleanup (brew, pip cache, old logs, trash)
- Power controls (sleep, restart, shutdown)
- Plugin management (brew install/uninstall)
- LaunchD agent management

### Telegram Bot
- Secure pairing protocol (8-char crypto codes, 5-min TTL, rate limited)
- Inline keyboard UI with emoji icons
- Onboarding wizard for first-time setup
- Settings screen for managing project directories
- Real-time notifications for session events (blocked, trust errors, exits)
- Machine discovery notifications with approve/deny buttons

## Quickstart

See [QUICKSTART.md](QUICKSTART.md) for step-by-step setup instructions.

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Main menu with system status |
| `/pair <code>` | Pair this device |
| `/unpair` | Remove pairing |
| `/projects` | Jump to projects menu |
| `/sessions` | Jump to sessions menu |
| `/maintenance` | Jump to maintenance menu |
| `/addmachine` | Manually register a remote machine |

### Menu Navigation

```
Main Menu
  +-- 📂 Projects (browse, search, launch, experiment, terminal)
  +-- ➕ New Project (scaffold from templates)
  +-- ⚡ Sessions (list, approve/deny prompts, stop, attach)
  +-- 🔧 Maintenance (status, git, cleanup, processes, power, plugins)
  +-- 💻 Machines (list, approve/deny, remove — multi-machine only)
  +-- ⚙️ Settings (project dirs, Claude CLI status, onboarding)
```

## Web Terminal

Tap **Terminal** on any project to get a browser-based shell:

1. Telegram sends you a URL like `http://10.13.1.10:9247/aB3xK4Dx2p/`
2. Open in any browser — straight into the terminal
3. Token in the URL path acts as authentication
4. Terminal auto-closes after disconnect or 30 minutes

Tap **Attach** on a running session to connect to the live Claude Code tmux session.

## Sprint Workflow

### Planning (You + Opus in Claude Code)

```
You: "Write a PRD for <what you want> and save to .taskmaster/docs/prd.txt"
You: "Use Task Master to parse the PRD into tasks and expand subtasks"
```

Opus does the planning using Task Master's MCP tools.

### Execution (Gemma 4 via OpenCode)

```bash
sprint status    # View task dashboard
sprint next      # Execute next task with Gemma 4
sprint run       # Execute ALL tasks autonomously
sprint done [id] # Mark task as done
sprint skip [id] # Defer a task
```

### Review (You + Opus)

```
You: "What changed? Run tests. Fix any issues."
You: "Commit and push"
```

## API Reference

All endpoints require `X-API-Key` header unless noted. Base: `http://localhost:8420/api/v1`

### Health & Pairing

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check — no auth, returns machine name and registration status |
| POST | `/pair-hub` | Node-to-hub pairing — one-time, unauthenticated |

### Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/projects` | List projects (optional `?search=` filter) |
| GET | `/projects/{slug}` | Project detail |

### Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/sessions` | Start Claude RC session (`experiment` flag for worktree mode) |
| GET | `/sessions` | List active sessions |
| GET | `/sessions/{id}` | Session detail and status |
| POST | `/sessions/{id}/respond` | Send y/n to blocked session |
| DELETE | `/sessions/{id}` | Stop session |
| POST | `/sessions/trust-and-launch` | Auto-trust workspace then launch session |

### Terminal

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/terminal` | Start web terminal (returns URL with embedded token) |
| POST | `/terminal/attach/{session_id}` | Attach terminal to running session |
| GET | `/terminal` | List active terminals |
| DELETE | `/terminal/{id}` | Stop terminal |

### Scaffold

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/scaffold/templates` | List available templates |
| POST | `/scaffold` | Create new project from template |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/system/status` | CPU, RAM, process count |
| GET | `/system/processes` | Top processes (optional `?limit=`) |
| POST | `/system/processes/{pid}/kill` | Kill process |
| GET | `/system/launchd` | List LaunchD agents |
| POST | `/system/launchd/{label}/{action}` | Start/stop agent |
| GET | `/system/git/status` | Git status across all repos |
| POST | `/system/git/pull-all` | Pull all repos (async job) |
| POST | `/system/git/prune` | Prune merged branches (async job) |
| POST | `/system/cleanup` | Run cleanup tasks (async job) |
| GET | `/system/jobs/{id}` | Check background job status |
| GET | `/system/plugins` | List brew packages |
| POST | `/system/plugins/install` | Install package |
| DELETE | `/system/plugins/{package}` | Uninstall package |

### Power

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/power/shutdown` | Shutdown machine |
| POST | `/power/restart` | Restart machine |
| POST | `/power/sleep` | Sleep machine |

### Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/settings` | Configuration summary |
| POST | `/settings/project-roots` | Add/remove project directory |
| GET | `/settings/detect-dirs` | Find common dev directories |

### Telegram

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/telegram/status` | Bot status and paired users |
| POST | `/telegram/pair-code` | Generate pairing code |

## Security

- **API auth**: Constant-time key comparison (`hmac.compare_digest`), rejects default keys, rate limited (100 req/min per IP)
- **Telegram**: 8-char crypto-random pairing codes, 5-min TTL, rotated on each generation
- **Hub pairing**: One-time key exchange, file-locked to prevent races, `.hub_paired` flag prevents re-pairing
- **CORS**: Disabled (empty allow_origins)
- **Swagger/Redoc**: Disabled in production
- **Process kill**: Restricted to current user's PIDs
- **LaunchD**: Restricted to `com.b2.*` agents
- **Brew packages**: Validated against `^[a-z0-9@._+-]+$`
- **Scaffold paths**: Validated against configured project roots
- **Web terminals**: Random port (9000-9999) + token-in-URL + single-use + 30min timeout
- **Session data**: `sessions.json` written with 0600 permissions
- **Shell commands**: All user input escaped via `shlex.quote`

## Configuration

| File | Purpose |
|------|---------|
| `backend/.env` | API key, Telegram token, project roots, Claude path, machine name |
| `backend/settings.json` | Runtime project directory config (managed via Telegram Settings) |
| `.taskmaster/config.json` | Task Master model config (Gemma 4 endpoint) |
| `~/.config/opencode/opencode.json` | OpenCode model config |
| `backend/com.b2.claude-launcher.plist` | macOS LaunchD service |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | *(required)* | API authentication key (must not be "changeme") |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8420` | Server port |
| `TELEGRAM_ENABLED` | `false` | Enable Telegram bot |
| `TELEGRAM_BOT_TOKEN` | — | Bot token from @BotFather |
| `MACHINE_NAME` | hostname | Identity for Tailscale discovery |
| `TAILSCALE_BIN` | auto-detect | Path to tailscale CLI |
| `PROJECT_ROOTS` | `~/Developer/mine` | Comma-separated project directories |
| `CLAUDE_BIN` | `~/.local/bin/claude` | Path to Claude CLI |

## Project Templates

| Template | Key | Contents |
|----------|-----|----------|
| Android App (Kotlin) | `android` | CLAUDE.md, build.gradle.kts, settings.gradle.kts |
| CLI Tool (Python) | `cli_python` | CLAUDE.md, pyproject.toml |
| Website | `website` | CLAUDE.md, index.html |
| Cloud (Terraform) | `cloud_terraform` | CLAUDE.md, main.tf |
| Hybrid Cloud+Mobile | `hybrid` | CLAUDE.md |
| API Service (FastAPI) | `fastapi` | CLAUDE.md, pyproject.toml |

All templates include sprint workflow instructions and Task Master configuration.

## Dependencies

### Python (backend/requirements.txt)

| Package | Purpose |
|---------|---------|
| fastapi | Web framework |
| uvicorn | ASGI server |
| pydantic / pydantic-settings | Data validation and config |
| psutil | System monitoring (CPU, RAM, processes) |
| python-dotenv | .env file loading |
| python-telegram-bot | Telegram API client |
| httpx | Async HTTP client (multi-machine comms) |

### System

| Tool | Purpose | Install |
|------|---------|---------|
| tmux | Session management | `brew install tmux` |
| ttyd | Web terminal | `brew install ttyd` |
| tailscale | Multi-machine networking | macOS App Store |
| claude | Claude Code CLI | [anthropic.com](https://docs.anthropic.com/en/docs/claude-code) |
| task-master-ai | Sprint task management | `npm install -g task-master-ai` |
| opencode | Local LLM execution | `brew install anomalyco/tap/opencode` |

## License

MIT
