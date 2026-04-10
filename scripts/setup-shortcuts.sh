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
sudo tee "$BIN_DIR/update-feta" > /dev/null << EOF
#!/bin/bash
# Update File Agent to latest version and restart the service
set -euo pipefail
cd "$PROJECT_DIR"
echo "🔄 Updating File Agent..."
bash update.sh
echo "♻️  Restarting service..."
bash restart-feta.sh
echo "✅ File Agent updated and restarted!"
EOF
sudo chmod +x "$BIN_DIR/update-feta"
log_success "update-feta → downloads latest code + restarts service"

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

# ── Done ─────────────────────────────────────────────────────────────
echo
echo -e "${GREEN}Done!${NC} You can now run from anywhere:"
echo "  update-feta    # pull latest + restart"
echo "  restart-feta   # just restart"
