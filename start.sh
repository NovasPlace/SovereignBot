#!/usr/bin/env bash
# Sovereign — start script
# Usage: ./start.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# Load .env if present
ENV_FILE="$SCRIPT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "⚠️  No .env found. Copy sovereign/.env.example → sovereign/.env and fill it in."
    exit 1
fi

# Sanity check
if [ -z "$SOVEREIGN_BOT_TOKEN" ]; then
    echo "❌ SOVEREIGN_BOT_TOKEN is empty. Add it to sovereign/.env"
    exit 1
fi

# Kill any stale Sovereign processes and free ports
echo "🧹 Cleaning stale processes..."
pkill -f "python.*sovereign\.(daemon|aleph_cli)" 2>/dev/null || true
for port in 8800 3100 3200 3456 8600; do
    fuser -k "$port/tcp" 2>/dev/null || true
done
sleep 1

echo "🟢 Sovereign booting..."
echo "   Model:   ${SOVEREIGN_MODEL}"
echo "   Ollama:  ${SOVEREIGN_OLLAMA_URL}"
echo ""
"$SCRIPT_DIR/.venv/bin/python" -m sovereign.aleph_cli "$@"
