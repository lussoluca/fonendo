#!/bin/sh
# Run Claude Code through the fonendo proxy with the plugin loaded.
#
# The proxy itself is a long-running service (see install-proxy-service.sh);
# this script only checks that it is reachable, points Claude Code at it,
# and loads the plugin from this checkout. Extra arguments pass through to
# `claude`, so run it from any project directory.
#
# Usage: claude-logged.sh [claude arguments...]
# Port override: FONENDO_PROXY_PORT=9999 claude-logged.sh

set -eu

PORT="${FONENDO_PROXY_PORT:-8484}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
UI_URL="http://127.0.0.1:$PORT/__fonendo/"

if ! curl -fsS -o /dev/null --max-time 2 "$UI_URL"; then
    echo "fonendo proxy is not listening on 127.0.0.1:$PORT" >&2
    echo "install it as a login service:  $SCRIPT_DIR/install-proxy-service.sh" >&2
    echo "or start it by hand:            python3 $SCRIPT_DIR/proxy.py --port $PORT" >&2
    exit 1
fi

echo "inspector UI: $UI_URL"
ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT" exec claude --plugin-dir "$PLUGIN_DIR" "$@"
