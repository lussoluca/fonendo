#!/bin/sh
# Start the logging proxy, then run Claude Code through it.
# All model traffic (raw request payloads and responses) is captured to
# ~/.claude/fonendo/raw/ and browsable live in the inspector UI.
# The proxy is stopped when Claude exits.
#
# Usage: claude-logged.sh [claude arguments...]
# Port override: FONENDO_PROXY_PORT=9999 claude-logged.sh

set -eu

PORT="${FONENDO_PROXY_PORT:-8484}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$SCRIPT_DIR/../web"

# Build the inspector UI on first run.
if [ ! -d "$WEB_DIR/dist" ] && command -v npm >/dev/null 2>&1; then
    echo "building inspector UI (first run)..."
    (cd "$WEB_DIR" && npm install --silent && npm run build --silent)
fi

# The proxy must not write to this terminal: Claude Code's TUI owns it, and
# stray output would leak into the input box. Log to a file instead.
PROXY_LOG="$HOME/.claude/fonendo/proxy.log"
mkdir -p "$(dirname "$PROXY_LOG")"

python3 "$SCRIPT_DIR/proxy.py" --port "$PORT" >"$PROXY_LOG" 2>&1 &
PROXY_PID=$!
trap 'kill "$PROXY_PID" 2>/dev/null || true' EXIT INT TERM

# Give the proxy a moment to bind before Claude connects.
sleep 1

echo "inspector UI: http://127.0.0.1:$PORT/__fonendo/"
echo "proxy log:    $PROXY_LOG"
ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT" claude "$@"
