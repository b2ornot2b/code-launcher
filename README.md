# Claude Code Launcher

Launch and manage Claude Code remote-control sessions from your phone. Create projects, start coding sessions, monitor your system, and get a browser-based terminal -- all from Telegram. Then delegate development sprints to a local LLM while you review from the Claude Code mobile app.

## Architecture

```
Phone (Telegram)
  |
  v
FastAPI Backend (Mac:8420)
  |
  +---> claude remote-control (tmux sessions)
  +---> system management (processes, git, cleanup)
  +---> ttyd web terminals
  +---> project scaffolding
  |
  +---> Claude Code Mobile App (review & plan)
  +---> OpenCode + Gemma 4 (execute tasks)
  +---> SSH: tmux attach (direct access)
```

## Features

**Session Management**
- Launch Claude Code remote-control sessions from Telegram
- Sessions run in named tmux sessions (`ccl-<project>-<timestamp>`)
- Attach via SSH: `tmux attach -t ccl-<name>`
- Auto-detect workspace trust prompts -- approve from Telegram
- Experiment mode (git worktree isolation) for safe exploration
- Auto-cleanup of stale/dead tmux sessions

**Web Terminal**
- One-tap browser shell for any project from Telegram
- Token-in-URL authentication -- no login dialog
- Single-use, auto-expires after 30 minutes or disconnect
- Attach to running Claude Code sessions to watch live

**Project Management**
- Browse and search projects across configured directories
- Auto-detect project type via markers (.git, package.json, etc.)
- Create new projects from 6 templates (Android, Python CLI, Website, Cloud, Hybrid, FastAPI)
- Projects auto-initialized with Task Master + local LLM config

**Sprint Workflow**
- Plan sprints with Opus (Claude Code) using Task Master MCP tools
- Execute tasks autonomously with local Gemma 4 via OpenCode
- `sprint next` / `sprint run` for hands-off execution

**System Maintenance**
- System status (CPU, RAM, disk, battery, network)
- Process management (list, kill)
- Git operations (status all repos, pull all, prune branches)
- Cleanup (brew, pip cache, old logs)
- Power controls (sleep, restart)
- Plugin management (brew install/uninstall)
- LaunchD agent management

**Telegram Bot**
- Secure pairing protocol (8-char crypto codes, rate limited)
- Inline keyboard UI with emoji icons
- Onboarding wizard for first-time setup
- Settings screen for managing project directories
- Real-time notifications for session events

## Quickstart

### Prerequisites

- macOS with Homebrew
- Python 3.9+
- Claude Code CLI (`claude`) installed and logged in
- A Telegram account

### 1. Clone and setup

```bash
git clone <repo-url> b2-claude-launcher-telegram-bot
cd b2-claude-launcher-telegram-bot/backend
./setup_venv.sh
```

This creates a virtual environment, installs dependencies, and generates an API key.

### 2. Create a Telegram bot

1. Open Telegram, message `@BotFather`
2. Send `/newbot`, pick a name and username
3. Copy the bot token

### 3. Configure

Edit `backend/.env`:

```bash
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<your-token-from-botfather>
```

### 4. Start the server

```bash
cd backend && ./run.sh
```

### 5. Pair your phone

```bash
# Get a pairing code
curl -X POST http://localhost:8420/api/v1/telegram/pair-code \
  -H "X-API-Key: <your-api-key>"
```

Then in Telegram, message your bot: `/pair <code>`

### 6. Launch a session

In Telegram: tap **Projects** > pick a project > **Launch**

Open the Claude Code mobile app -- your session appears there.

### Optional: Install sprint tools

For the automated sprint workflow with local LLMs:

```bash
# Install dependencies
brew install tmux ttyd node
npm install -g task-master-ai

# Install OpenCode
brew install anomalyco/tap/opencode

# Symlink sprint script
ln -sf $(pwd)/bin/sprint ~/.local/bin/sprint
```

### Optional: Boot-on-startup

```bash
cp backend/com.b2.claude-launcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.b2.claude-launcher.plist
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Main menu with live system status |
| `/pair <code>` | Pair this device |
| `/unpair` | Remove pairing |

### Menu Navigation

```
Main Menu
  +-- Projects (browse, search, launch, experiment, terminal)
  +-- New Project (scaffold from templates)
  +-- Sessions (list, attach, stop)
  +-- Maintenance (status, git, cleanup, processes, power)
  +-- Settings (project dirs, Claude CLI status)
```

## Web Terminal

Tap **Terminal** on any project to get a browser-based shell:

1. Telegram sends you a URL like `http://10.13.1.10:9247/aB3xK4Dx2p/`
2. Open in any browser -- straight into the terminal
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

All endpoints require `X-API-Key` header. Base: `http://localhost:8420/api/v1`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check (no auth) |
| GET | `/projects` | List projects |
| GET | `/projects/{slug}` | Project detail |
| POST | `/sessions` | Start Claude RC session |
| GET | `/sessions` | List active sessions |
| GET | `/sessions/{id}` | Session detail |
| POST | `/sessions/{id}/respond` | Send y/n to blocked session |
| DELETE | `/sessions/{id}` | Stop session |
| POST | `/terminal` | Start web terminal |
| POST | `/terminal/attach/{session_id}` | Attach terminal to session |
| GET | `/terminal` | List terminals |
| DELETE | `/terminal/{id}` | Stop terminal |
| GET | `/scaffold/templates` | List templates |
| POST | `/scaffold` | Create new project |
| GET | `/system/status` | System info |
| GET | `/system/processes` | Top processes |
| POST | `/system/processes/{pid}/kill` | Kill process |
| GET | `/system/launchd` | List LaunchD agents |
| POST | `/system/launchd/{label}/{action}` | Start/stop agent |
| GET | `/system/git/status` | Git status all repos |
| POST | `/system/git/pull-all` | Pull all repos |
| POST | `/system/git/prune` | Prune merged branches |
| POST | `/system/cleanup` | Run cleanup tasks |
| GET | `/system/plugins` | List brew packages |
| POST | `/system/plugins/install` | Install package |
| DELETE | `/system/plugins/{package}` | Uninstall package |
| GET | `/system/jobs/{id}` | Check background job |
| POST | `/power/{action}` | Shutdown/restart/sleep |
| GET | `/telegram/status` | Telegram bot status |
| POST | `/telegram/pair-code` | Generate pairing code |

## Security

- **API auth**: Constant-time key comparison, rejects default keys, rate limited (100 req/min)
- **Telegram**: 8-char crypto-random pairing codes, 5-attempt rate limit, atomic file writes
- **CORS**: Disabled (empty allow_origins)
- **Swagger/Redoc**: Disabled in production
- **Process kill**: Restricted to current user's PIDs
- **LaunchD**: Restricted to `com.b2.*` agents
- **Brew packages**: Validated against `^[a-z0-9@._+-]+$`
- **Scaffold paths**: Validated against configured project roots
- **Web terminals**: Random port + token-in-URL + single-use + 30min timeout
- **Session data**: `sessions.json` written with 0600 permissions
- **Shell commands**: All user input escaped via `shlex.quote`

## Configuration

| File | Purpose |
|------|---------|
| `backend/.env` | API key, Telegram token, project roots, Claude path, LLM key |
| `backend/settings.json` | Runtime project directory config (managed via Telegram Settings) |
| `.taskmaster/config.json` | Task Master model config (Gemma 4 endpoint) |
| `~/.config/opencode/opencode.json` | OpenCode model config |
| `backend/com.b2.claude-launcher.plist` | macOS LaunchD service |

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

## License

MIT
