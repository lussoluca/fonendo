#!/bin/sh
# Install the fonendo proxy as a user service that starts at login.
# macOS: a launchd LaunchAgent. Linux: a systemd user unit.
# Builds the inspector UI first if web/dist is missing (needs Node).
#
# Usage: install-proxy-service.sh [--uninstall]
# Port override: FONENDO_PROXY_PORT=9999 install-proxy-service.sh

set -eu

PORT="${FONENDO_PROXY_PORT:-8484}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$SCRIPT_DIR/../web"
PYTHON="$(command -v python3)"
LOG_DIR="$HOME/.claude/fonendo"
LABEL="com.fonendo.proxy"
mkdir -p "$LOG_DIR"

if [ "${1:-}" != "--uninstall" ] && [ ! -d "$WEB_DIR/dist" ] && command -v npm >/dev/null 2>&1; then
    echo "building inspector UI..."
    (cd "$WEB_DIR" && npm install --silent && npm run build --silent)
fi

case "$(uname)" in
Darwin)
    PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
    DOMAIN="gui/$(id -u)"
    if [ "${1:-}" = "--uninstall" ]; then
        launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
        rm -f "$PLIST"
        echo "removed $PLIST"
        exit 0
    fi
    mkdir -p "$(dirname "$PLIST")"
    cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$SCRIPT_DIR/proxy.py</string>
        <string>--port</string>
        <string>$PORT</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$LOG_DIR/proxy.log</string>
    <key>StandardErrorPath</key><string>$LOG_DIR/proxy.log</string>
</dict>
</plist>
PLIST
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "installed $PLIST"
    ;;
Linux)
    UNIT_DIR="$HOME/.config/systemd/user"
    UNIT="$UNIT_DIR/fonendo-proxy.service"
    if [ "${1:-}" = "--uninstall" ]; then
        systemctl --user disable --now fonendo-proxy.service 2>/dev/null || true
        rm -f "$UNIT"
        systemctl --user daemon-reload
        echo "removed $UNIT"
        exit 0
    fi
    mkdir -p "$UNIT_DIR"
    cat >"$UNIT" <<UNIT
[Unit]
Description=fonendo logging proxy for Claude Code

[Service]
ExecStart=$PYTHON $SCRIPT_DIR/proxy.py --port $PORT
Restart=always
StandardOutput=append:$LOG_DIR/proxy.log
StandardError=append:$LOG_DIR/proxy.log

[Install]
WantedBy=default.target
UNIT
    systemctl --user daemon-reload
    systemctl --user enable --now fonendo-proxy.service
    echo "installed $UNIT"
    ;;
*)
    echo "unsupported platform: $(uname)" >&2
    exit 1
    ;;
esac

echo "inspector UI: http://127.0.0.1:$PORT/__fonendo/"
echo "proxy log:    $LOG_DIR/proxy.log"
