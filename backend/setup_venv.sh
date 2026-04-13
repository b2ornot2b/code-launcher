#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "Creating virtual environment..."
uv venv .venv
source .venv/bin/activate

echo "Installing dependencies..."
uv pip install -r requirements.txt

echo "Generating API key..."
if [ ! -f .env ]; then
    API_KEY=$(python3 -c "import secrets; print(secrets.token_hex(16))")
    cp .env.example .env
    sed -i '' "s/API_KEY=changeme/API_KEY=$API_KEY/" .env
    echo ""
    echo "=== Your API key ==="
    echo "$API_KEY"
    echo "===================="
    echo "Save this key — you'll need it for the mobile app."
else
    echo ".env already exists, skipping."
fi

echo ""
echo "=== Telegram Bot Setup (optional) ==="
echo "1. Open Telegram and message @BotFather"
echo "2. Send /newbot and follow the prompts"
echo "3. Copy the bot token"
echo "4. Edit .env and set:"
echo "   TELEGRAM_ENABLED=true"
echo "   TELEGRAM_BOT_TOKEN=<your-token>"
echo ""
echo "Setup complete. Run: ./run.sh"
