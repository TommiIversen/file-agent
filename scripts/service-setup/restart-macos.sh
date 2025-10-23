#!/bin/bash
# Restart File Transfer Agent macOS service

SERVICE_NAME="com.fileagent.service"
PLIST_NAME="${SERVICE_NAME}.plist"

# Detect if running as root (system-wide) or user (user agent)
if [[ $EUID -eq 0 ]]; then
    SERVICE_DIR="/Library/LaunchDaemons"
else
    SERVICE_DIR="$HOME/Library/LaunchAgents"
fi

PLIST_PATH="$SERVICE_DIR/$PLIST_NAME"

if [[ ! -f "$PLIST_PATH" ]]; then
    echo "[ERROR] Service plist not found: $PLIST_PATH"
    exit 1
fi

echo "Restarting File Transfer Agent service..."
launchctl unload "$PLIST_PATH"
sleep 2
launchctl load "$PLIST_PATH"
echo "[SUCCESS] Service restarted."

# Show status
echo "Service status:"
launchctl list | grep "$SERVICE_NAME" || echo "Service not found in process list"
