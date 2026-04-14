#!/bin/bash
# File Agent — One-command installer for macOS
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/TommiIversen/file-agent/main/install.sh | bash
#
#   # Install specific version:
#   curl -fsSL ... | bash -s -- --version v1.2.0
#
#   # Upgrade (auto-detected if already installed, or explicit):
#   curl -fsSL ... | bash -s -- --upgrade
#
#   # Uninstall:
#   curl -fsSL ... | bash -s -- --uninstall

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────
GITHUB_REPO="TommiIversen/file-agent"
INSTALL_DIR="/usr/local/share/file-agent"
BIN_LINK="/usr/local/bin/file-agent"
SERVICE_NAME="com.fileagent.service"
PLIST_NAME="${SERVICE_NAME}.plist"
PLIST_DIR="$HOME/Library/LaunchAgents"
BROWSER_PLIST="com.fileagent.openbrowser.plist"

# New unified data directory (macOS best practice)
DATA_DIR="$HOME/Library/Application Support/FileAgent"
LOG_DIR="$DATA_DIR/logs"
CONFIG_DIR="$DATA_DIR/config"
DB_DIR="$DATA_DIR/data"

# Legacy locations (for migration)
LEGACY_LOG_DIR="$HOME/Library/Logs/file-agent"
LEGACY_CONFIG_DIR="$HOME/.config/file-agent"

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}  ✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ── Parse arguments ──────────────────────────────────────────────────
VERSION=""
UPGRADE=false
UNINSTALL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --version)  VERSION="$2"; shift 2 ;;
        --upgrade)  UPGRADE=true; shift ;;
        --uninstall) UNINSTALL=true; shift ;;
        *) log_error "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Uninstall ────────────────────────────────────────────────────────
do_uninstall() {
    echo
    log_info "Uninstalling File Agent..."

    # Stop service
    if launchctl list 2>/dev/null | grep -q "$SERVICE_NAME"; then
        launchctl bootout "gui/$(id -u)/$SERVICE_NAME" 2>/dev/null \
            || launchctl unload "$PLIST_DIR/$PLIST_NAME" 2>/dev/null \
            || true
        log_success "Service stopped"
    fi

    # Remove browser agent
    if [[ -f "$PLIST_DIR/$BROWSER_PLIST" ]]; then
        launchctl unload "$PLIST_DIR/$BROWSER_PLIST" 2>/dev/null || true
        rm -f "$PLIST_DIR/$BROWSER_PLIST"
        log_success "Browser launch agent removed"
    fi

    # Remove plist
    rm -f "$PLIST_DIR/$PLIST_NAME"
    log_success "Service plist removed"

    # Remove binary
    sudo rm -rf "$INSTALL_DIR"
    sudo rm -f "$BIN_LINK"
    log_success "Binary removed"

    log_success "File Agent uninstalled. Data ($DATA_DIR) was kept."
    log_info "To remove all data: rm -rf \"$DATA_DIR\""
    # Also mention legacy dirs if they exist
    [[ -d "$LEGACY_CONFIG_DIR" ]] && log_info "Legacy config still at: $LEGACY_CONFIG_DIR"
    [[ -d "$LEGACY_LOG_DIR" ]]    && log_info "Legacy logs still at: $LEGACY_LOG_DIR"
    exit 0
}

[[ "$UNINSTALL" == true ]] && do_uninstall

# ── Auto-detect upgrade ─────────────────────────────────────────────
if [[ -d "$INSTALL_DIR" ]] && [[ "$UPGRADE" == false ]]; then
    log_info "Existing installation detected — running as upgrade."
    UPGRADE=true
fi

# ── Resolve version ─────────────────────────────────────────────────
if [[ -z "$VERSION" ]]; then
    log_info "Finding latest release..."
    # Try GitHub API first, fall back to redirect-based detection (avoids 403 rate limits)
    # Note: pipefail means a failing curl kills the whole pipeline, so we
    # isolate it with `|| true` to let the empty-VERSION check handle failure.
    VERSION=$(curl -fsSL "https://api.github.com/repos/$GITHUB_REPO/releases/latest" 2>/dev/null \
        | grep '"tag_name"' | head -1 | sed -E 's/.*"([^"]+)".*/\1/' | tr -d '\r') || true
    if [[ -z "$VERSION" ]]; then
        log_warn "GitHub API rate-limited, using redirect fallback..."
        VERSION=$(curl -fsSIL "https://github.com/$GITHUB_REPO/releases/latest" 2>/dev/null \
            | grep -i '^location:' | tail -1 | sed -E 's|.*/tag/([^ \t\r]+).*|\1|' | tr -d '\r') || true
    fi
    if [[ -z "$VERSION" ]]; then
        log_error "Could not determine latest version. Use --version vX.Y.Z"
        exit 1
    fi
fi
log_info "Version: $VERSION"

# ── Detect architecture ─────────────────────────────────────────────
ARCH=$(uname -m)
case "$ARCH" in
    arm64)  ASSET_ARCH="arm64" ;;
    x86_64) ASSET_ARCH="x86_64" ;;
    *)      log_error "Unsupported architecture: $ARCH"; exit 1 ;;
esac
ASSET_NAME="file-agent-${VERSION}-macos-${ASSET_ARCH}.tar.gz"
DOWNLOAD_URL="https://github.com/$GITHUB_REPO/releases/download/$VERSION/$ASSET_NAME"

# ── Stop existing service (upgrade) ─────────────────────────────────
if [[ "$UPGRADE" == true ]] || [[ -d "$INSTALL_DIR" ]]; then
    if launchctl list 2>/dev/null | grep -q "$SERVICE_NAME"; then
        log_info "Stopping existing service..."
        # Try modern API first, fall back to legacy
        launchctl bootout "gui/$(id -u)/$SERVICE_NAME" 2>/dev/null \
            || launchctl unload "$PLIST_DIR/$PLIST_NAME" 2>/dev/null \
            || true
        sleep 1
    fi
fi

# ── Download & extract ───────────────────────────────────────────────
log_info "Downloading $ASSET_NAME..."
TMPDIR_DL=$(mktemp -d)
trap "rm -rf $TMPDIR_DL" EXIT

if ! curl -fSL --progress-bar -o "$TMPDIR_DL/file-agent.tar.gz" "$DOWNLOAD_URL"; then
    log_error "Download failed. Check that release $VERSION exists at:"
    log_error "  https://github.com/$GITHUB_REPO/releases/tag/$VERSION"
    exit 1
fi

log_info "Extracting..."
tar xzf "$TMPDIR_DL/file-agent.tar.gz" -C "$TMPDIR_DL"

# ── Install binary ───────────────────────────────────────────────────
log_info "Installing to $INSTALL_DIR (requires sudo)..."
sudo mkdir -p "$INSTALL_DIR"
sudo rm -rf "$INSTALL_DIR"/*
sudo cp -R "$TMPDIR_DL/file-agent/"* "$INSTALL_DIR/"
sudo chmod +x "$INSTALL_DIR/file-agent"
sudo ln -sf "$INSTALL_DIR/file-agent" "$BIN_LINK"
log_success "Binary installed"

# ── Create directories ───────────────────────────────────────────────
mkdir -p "$LOG_DIR" "$CONFIG_DIR" "$DB_DIR" "$PLIST_DIR"
log_success "Data directory: $DATA_DIR"

# ── Migrate from legacy locations ────────────────────────────────────
MIGRATED=false

# Migrate config files from ~/.config/file-agent/ → DATA_DIR/config/
if [[ -d "$LEGACY_CONFIG_DIR" ]]; then
    for f in "$LEGACY_CONFIG_DIR"/*-settings.env; do
        [[ -f "$f" ]] || continue
        fname=$(basename "$f")
        if [[ ! -f "$CONFIG_DIR/$fname" ]]; then
            cp "$f" "$CONFIG_DIR/$fname"
            log_success "Migrated config: $fname"
            MIGRATED=true
        fi
    done
fi

# Migrate logs from ~/Library/Logs/file-agent/ → DATA_DIR/logs/
if [[ -d "$LEGACY_LOG_DIR" ]]; then
    for f in "$LEGACY_LOG_DIR"/file_agent.log*; do
        [[ -f "$f" ]] || continue
        fname=$(basename "$f")
        if [[ ! -f "$LOG_DIR/$fname" ]]; then
            cp "$f" "$LOG_DIR/$fname"
            MIGRATED=true
        fi
    done
    if [[ "$MIGRATED" == true ]]; then
        log_success "Migrated logs to $LOG_DIR"
    fi
fi

# Migrate database from various legacy locations
for legacy_db in \
    "$HOME/data/file-agent.db" \
    "$HOME/file-agent.db" \
    "$LEGACY_CONFIG_DIR/file-agent.db" \
    ; do
    if [[ -f "$legacy_db" ]] && [[ ! -f "$DB_DIR/file-agent.db" ]]; then
        cp "$legacy_db" "$DB_DIR/file-agent.db"
        log_success "Migrated database from $legacy_db"
        MIGRATED=true
        break
    fi
done

# Clean up legacy directories if migration happened
if [[ "$MIGRATED" == true ]]; then
    log_info "Legacy data migrated. Old locations can be removed manually:"
    [[ -d "$LEGACY_CONFIG_DIR" ]] && log_info "  rm -rf $LEGACY_CONFIG_DIR"
    [[ -d "$LEGACY_LOG_DIR" ]]    && log_info "  rm -rf $LEGACY_LOG_DIR"
fi

# ── Config note ──────────────────────────────────────────────────────
# The app auto-generates a host-specific <hostname>-settings.env on
# first start.  No need to seed a generic settings.env here.
HOSTNAME_SHORT=$(hostname -s 2>/dev/null || hostname | cut -d. -f1)
HOST_CONFIG="$CONFIG_DIR/${HOSTNAME_SHORT}-settings.env"
if [[ -f "$HOST_CONFIG" ]]; then
    log_info "Existing host config preserved at $HOST_CONFIG"
else
    log_info "Host config will be auto-generated on first start at:"
    log_info "  $HOST_CONFIG"
fi

# ── Create launchd plist ─────────────────────────────────────────────
log_info "Setting up launchd service..."

cat > "$PLIST_DIR/$PLIST_NAME" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$SERVICE_NAME</string>

    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/file-agent</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$HOME</string>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/file-agent-stdout.log</string>

    <key>StandardErrorPath</key>
    <string>$LOG_DIR/file-agent-stderr.log</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>$HOME</string>
    </dict>

    <key>ThrottleInterval</key>
    <integer>5</integer>
</dict>
</plist>
EOF
chmod 644 "$PLIST_DIR/$PLIST_NAME"
log_success "Service plist created"

# ── Create browser launch agent ──────────────────────────────────────
# Uses a wait-script that polls the server before opening the browser,
# so we don't get "Safari can't connect" on boot.
BROWSER_SCRIPT="$INSTALL_DIR/scripts/wait-and-open-browser.sh"
chmod +x "$BROWSER_SCRIPT" 2>/dev/null || true

# Remove stale plist from previous installs (avoids permission denied)
rm -f "$PLIST_DIR/$BROWSER_PLIST" 2>/dev/null || true

cat > "$PLIST_DIR/$BROWSER_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.fileagent.openbrowser</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${BROWSER_SCRIPT}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/browser-open.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/browser-open.log</string>
</dict>
</plist>
EOF
log_success "Browser launch agent created (with server-readiness check)"

# ── Start service ────────────────────────────────────────────────────
log_info "Starting service..."
# Try modern API first, fall back to legacy
if launchctl bootstrap "gui/$(id -u)" "$PLIST_DIR/$PLIST_NAME" 2>/dev/null; then
    true  # success
elif launchctl load "$PLIST_DIR/$PLIST_NAME" 2>/dev/null; then
    true  # legacy success
else
    log_warn "Could not start service automatically."
    log_warn "Try: launchctl load $PLIST_DIR/$PLIST_NAME"
    log_warn "Or run manually: file-agent"
fi

# Wait for launchd to register the service (fast check)
sleep 2
if launchctl list 2>/dev/null | grep -q "$SERVICE_NAME"; then
    log_success "Service is running"
else
    log_warn "Service may not have started. Check: launchctl list | grep fileagent"
fi

# ── Install shell shortcuts (update-feta, restart-feta) ──────────────
SHORTCUT_SCRIPT="$INSTALL_DIR/scripts/setup-shortcuts.sh"
if [[ -f "$SHORTCUT_SCRIPT" ]]; then
    log_info "Setting up shell shortcuts..."
    bash "$SHORTCUT_SCRIPT"
else
    log_warn "Shortcut script not found at $SHORTCUT_SCRIPT — skipping"
fi

# ── Health check (poll until ready, up to 30s) ───────────────────────
log_info "Waiting for Web UI to become ready..."
HEALTH_OK=false
for i in $(seq 1 15); do
    if curl -sf --max-time 2 http://localhost:8000/health > /dev/null 2>&1; then
        HEALTH_OK=true
        break
    fi
    sleep 2
done

if [[ "$HEALTH_OK" == true ]]; then
    log_success "Web UI is live at http://localhost:8000"
else
    log_warn "Web UI not responding after 30s (may still be starting). Check logs:"
    log_warn "  tail -f $LOG_DIR/file-agent.log"
fi

# ── Done ─────────────────────────────────────────────────────────────
echo
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  File Agent $VERSION installed successfully!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo
echo "  Web UI:     http://localhost:8000"
echo "  Data:       $DATA_DIR/"
echo "    Config:   $CONFIG_DIR/"
echo "    Logs:     $LOG_DIR/"
echo "    Database: $DB_DIR/"
echo "  Binary:     $INSTALL_DIR/"
echo
echo "  Commands:"
echo "    file-agent              # Run manually"
echo "    launchctl list | grep fileagent"
echo "    tail -f $LOG_DIR/file-agent.log"
echo
echo "  Upgrade:    curl -fsSL https://raw.githubusercontent.com/$GITHUB_REPO/main/install.sh | bash"
echo "              (auto-detects existing installation)"
echo "  Uninstall:  curl -fsSL https://raw.githubusercontent.com/$GITHUB_REPO/main/install.sh | bash -s -- --uninstall"
echo
echo -e "${YELLOW}  NOTE: On first launch macOS will ask to allow local network access.${NC}"
echo -e "${YELLOW}        Click 'Allow' — File Agent needs this to talk to tally lights,${NC}"
echo -e "${YELLOW}        Just In Engine, and serve the web UI.${NC}"
echo
