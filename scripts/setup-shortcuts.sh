#!/bin/bash
# Creates 'update-feta' and 'restart-feta' shell shortcuts.
# Run once after cloning or updating the repo:
#   bash scripts/setup-shortcuts.sh

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}  ✓${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

# Resolve the project directory (parent of scripts/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

BIN_DIR="/usr/local/bin"

# ── update-feta ──────────────────────────────────────────────────────
log_info "Creating update-feta..."
sudo tee "$BIN_DIR/update-feta" > /dev/null << 'EOF'
#!/bin/bash
# Update File Agent to latest binary release and restart the service
# Usage: update-feta          # install latest stable
#        update-feta --beta   # install latest beta
set -eo pipefail
EXTRA_ARGS=""
for arg in "${@:-}"; do
    case "$arg" in
        --beta) EXTRA_ARGS="--beta" ;;
        "")     ;;
        *)      echo "Unknown option: $arg"; exit 1 ;;
    esac
done
if [[ -n "$EXTRA_ARGS" ]]; then
    echo "🔄 Updating File Agent (beta)..."
    curl -fsSL https://raw.githubusercontent.com/TommiIversen/file-agent/main/install.sh | bash -s -- --upgrade $EXTRA_ARGS
    echo "✅ File Agent updated to latest beta!"
else
    echo "🔄 Updating File Agent..."
    curl -fsSL https://raw.githubusercontent.com/TommiIversen/file-agent/main/install.sh | bash -s -- --upgrade
    echo "✅ File Agent updated and restarted!"
fi
EOF
sudo chmod +x "$BIN_DIR/update-feta"
log_success "update-feta → downloads latest binary release + restarts service (supports --beta)"

# ── restart-feta ─────────────────────────────────────────────────────
log_info "Creating restart-feta..."
sudo tee "$BIN_DIR/restart-feta" > /dev/null << EOF
#!/bin/bash
# Restart File Agent service
cd "$PROJECT_DIR"
exec bash restart-feta.sh
EOF
sudo chmod +x "$BIN_DIR/restart-feta"
log_success "restart-feta → restarts the launchd service"

# ── stop-feta ────────────────────────────────────────────────────────
log_info "Creating stop-feta..."
sudo tee "$BIN_DIR/stop-feta" > /dev/null << 'EOF'
#!/bin/bash
# Stop File Agent service (disable until next manual start/reboot)
set -eo pipefail
PLIST_USER="$HOME/Library/LaunchAgents/com.fileagent.service.plist"
PLIST_SYSTEM="/Library/LaunchDaemons/com.fileagent.service.plist"

if [ -f "$PLIST_USER" ]; then
    launchctl unload "$PLIST_USER" 2>/dev/null && echo "✅ File Agent stopped (user service)." || echo "⚠️  Service was not running."
elif [ -f "$PLIST_SYSTEM" ]; then
    sudo launchctl unload "$PLIST_SYSTEM" 2>/dev/null && echo "✅ File Agent stopped (system service)." || echo "⚠️  Service was not running."
else
    echo "❌ No File Agent service plist found."
    exit 1
fi
EOF
sudo chmod +x "$BIN_DIR/stop-feta"
log_success "stop-feta → stops the launchd service"

# ── Done ─────────────────────────────────────────────────────────────
echo
echo -e "${GREEN}Done!${NC} You can now run from anywhere:"
echo "  update-feta    # pull latest + restart"
echo "  restart-feta   # just restart"
echo "  stop-feta      # stop the service"
