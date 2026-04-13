# Quickstart

Get Claude Code Launcher running in under 5 minutes.

## Prerequisites

- macOS with Homebrew
- Python 3.9+
- Claude Code CLI (`claude`) installed and logged in
- A Telegram account

## 1. Clone and setup

```bash
git clone <repo-url> b2-claude-launcher-telegram-bot
cd b2-claude-launcher-telegram-bot/backend
./setup_venv.sh
```

This creates a virtual environment, installs dependencies, and generates an API key. Note the API key printed at the end.

## 2. Create a Telegram bot

1. Open Telegram, message `@BotFather`
2. Send `/newbot`, pick a name and username
3. Copy the bot token

## 3. Configure

Edit `backend/.env`:

```bash
API_KEY=<your-generated-api-key>
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<your-token-from-botfather>
PROJECT_ROOTS=~/Developer/mine    # comma-separated directories to scan
```

## 4. Start the server

```bash
cd backend && ./run.sh
```

Verify it's running:

```bash
curl http://localhost:8420/api/v1/health
```

## 5. Pair your phone

Generate a pairing code:

```bash
curl -X POST http://localhost:8420/api/v1/telegram/pair-code \
  -H "X-API-Key: <your-api-key>"
```

Then in Telegram, message your bot: `/pair <code>`

The bot will walk you through onboarding — configuring project directories and verifying the Claude CLI.

## 6. Launch your first session

In Telegram: tap **Projects** > pick a project > **Launch**

Open the Claude Code mobile app — your session appears there. You can also attach via SSH:

```bash
tmux attach -t ccl-<project-name>
```

## Optional: Web terminal

Install ttyd for browser-based terminals:

```bash
brew install tmux ttyd
```

Then tap **Terminal** on any project in Telegram to get a one-tap browser shell.

## Optional: Sprint workflow

For automated task execution with a local LLM:

```bash
# Install dependencies
brew install tmux node
npm install -g task-master-ai
brew install anomalyco/tap/opencode

# Symlink sprint script
ln -sf $(pwd)/bin/sprint ~/.local/bin/sprint
```

Then plan with Claude Code (Opus) and execute with:

```bash
sprint next      # Execute next task with Gemma 4
sprint run       # Execute all tasks autonomously
sprint status    # View task dashboard
```

## Optional: Multi-machine management

If you have multiple Macs on a Tailscale network:

1. Install and run Claude Code Launcher on each machine
2. The hub machine auto-discovers nodes via `tailscale status`
3. Approve new machines from Telegram when notified
4. Browse projects and manage sessions across all machines from a single bot

Nodes must have `registration_open: true` in their health endpoint (default until paired).

## Optional: Boot on startup

```bash
cp backend/com.b2.claude-launcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.b2.claude-launcher.plist
```

## Troubleshooting

**Server won't start**
- Check `backend/.env` exists and `API_KEY` is not "changeme"
- Ensure port 8420 is free: `lsof -i :8420`

**Telegram bot not responding**
- Verify `TELEGRAM_ENABLED=true` in `.env`
- Check the bot token is correct
- Make sure you've paired: `/pair <code>`

**Sessions not appearing in Claude Code mobile**
- Ensure `claude` CLI is on PATH (check with `which claude`)
- Verify Claude is logged in: `claude --version`

**Web terminal not opening**
- Install ttyd: `brew install ttyd`
- Check firewall allows the random port (9000-9999)

**Multi-machine discovery not working**
- Verify Tailscale is running on both machines
- Check that the remote machine's `/api/v1/health` returns `registration_open: true`
- Ensure port 8420 is accessible over Tailscale
