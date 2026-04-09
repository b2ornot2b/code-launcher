#!/bin/bash
# Setup script for a CCL node (non-hub machine).
# The hub will discover this node automatically via Tailscale.
set -e
cd "$(dirname "$0")"

echo "=== CCL Node Setup ==="
echo ""

# Create venv and install deps
echo "Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "Installing dependencies..."
pip install -r requirements.txt

# Generate .env for node
if [ ! -f .env ]; then
    API_KEY=$(python3 -c "import secrets; print(secrets.token_hex(16))")
    HOSTNAME=$(hostname)

    cat > .env <<EOF
# Auto-generated for CCL node
API_KEY=$API_KEY

# Node mode: no Telegram bot (hub handles that)
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=

# Machine name (defaults to hostname if not set)
# MACHINE_NAME=$HOSTNAME

# Project directories to scan (comma-separated)
PROJECT_ROOTS=$HOME/Developer

# Claude Code binary path
CLAUDE_BIN=$HOME/.local/bin/claude
EOF

    echo ""
    echo "=== Node configured ==="
    echo "Machine name: $HOSTNAME"
    echo "API key:      $API_KEY (stored in .env)"
    echo ""
else
    echo ".env already exists, skipping."
fi

echo ""
echo "=== Next Steps ==="
echo "1. Edit .env to set PROJECT_ROOTS to your project directories"
echo "2. Start the node:  ./run.sh"
echo "3. Your hub will discover this machine automatically via Tailscale"
echo "4. Approve the machine in Telegram when prompted"
echo ""
echo "Make sure Tailscale is running and connected to the same tailnet as your hub."
