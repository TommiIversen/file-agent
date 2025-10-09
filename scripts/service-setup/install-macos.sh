#!/bin/bash
# File Transfer Agent - macOS Service Setup Script
# This script sets up the File Transfer Agent as a macOS launchd service

set -e  # Exit on any error

# Configuration
SERVICE_NAME="com.fileagent.service"
PLIST_NAME="${SERVICE_NAME}.plist"
SERVICE_DIR="/Library/LaunchDaemons"  # System-wide service
USER_SERVICE_DIR="$HOME/Library/LaunchAgents"  # User service
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root for system service
check_permissions() {
    if [[ $EUID -eq 0 ]]; then
        log_info "Running as root - will install system-wide service"
        INSTALL_DIR="$SERVICE_DIR"
        SERVICE_USER="nobody"
    else
        log_info "Running as user - will install user service"
        INSTALL_DIR="$USER_SERVICE_DIR"
        SERVICE_USER="$(whoami)"
    fi
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check Python 3.8+
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is required but not installed"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log_info "Found Python version: $PYTHON_VERSION"
    
    if [[ $(echo "$PYTHON_VERSION < 3.8" | bc -l) -eq 1 ]]; then
        log_error "Python 3.8+ required, found $PYTHON_VERSION"
        exit 1
    fi
    
    # Check if project directory exists
    if [[ ! -d "$PROJECT_DIR" ]]; then
        log_error "Project directory not found: $PROJECT_DIR"
        exit 1
    fi
    
    # Check if virtual environment exists
    if [[ ! -d "$PROJECT_DIR/venv" ]]; then
        log_warning "Virtual environment not found, creating..."
        create_virtual_environment
    fi
    
    log_success "Prerequisites check passed"
}

# Create virtual environment and install dependencies
create_virtual_environment() {
    log_info "Creating virtual environment..."
    cd "$PROJECT_DIR"
    
    python3 -m venv venv
    source venv/bin/activate
    
    # Upgrade pip
    pip install --upgrade pip
    
    # Install dependencies
    if [[ -f "requirements.txt" ]]; then
        pip install -r requirements.txt
    else
        log_info "Installing basic dependencies..."
        pip install fastapi uvicorn aiofiles pydantic python-dotenv
    fi
    
    log_success "Virtual environment created and dependencies installed"
}

# Create the launch daemon plist file
create_plist_file() {
    log_info "Creating launchd plist file..."
    
    PYTHON_PATH="$PROJECT_DIR/venv/bin/python"
    WORK_DIR="$PROJECT_DIR"
    LOG_DIR="$PROJECT_DIR/logs"
    
    # Create logs directory if it doesn't exist
    mkdir -p "$LOG_DIR"
    
    # Create the plist content
    cat > "$INSTALL_DIR/$PLIST_NAME" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$SERVICE_NAME</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>app.main:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>8000</string>
        <string>--log-level</string>
        <string>info</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>$WORK_DIR</string>
    
    <key>StandardOutPath</key>
    <string>$LOG_DIR/file-agent.log</string>
    
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/file-agent-error.log</string>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    
    <key>UserName</key>
    <string>$SERVICE_USER</string>
    
    <key>GroupName</key>
    <string>staff</string>
    
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
        <key>PYTHONPATH</key>
        <string>$PROJECT_DIR</string>
    </dict>
    
    <!-- Auto-restart on crash -->
    <key>ThrottleInterval</key>
    <integer>30</integer>
    
    <!-- Network service - start after network is available -->
    <key>LaunchOnlyOnce</key>
    <false/>
</dict>
</plist>
EOF

    # Set proper permissions
    chmod 644 "$INSTALL_DIR/$PLIST_NAME"
    
    if [[ $EUID -eq 0 ]]; then
        chown root:wheel "$INSTALL_DIR/$PLIST_NAME"
    fi
    
    log_success "Plist file created: $INSTALL_DIR/$PLIST_NAME"
}

# Load the service
load_service() {
    log_info "Loading File Transfer Agent service..."
    
    # Unload if already loaded (for updates)
    if launchctl list | grep -q "$SERVICE_NAME"; then
        log_info "Service already loaded, unloading first..."
        launchctl unload "$INSTALL_DIR/$PLIST_NAME" 2>/dev/null || true
    fi
    
    # Load the service
    launchctl load "$INSTALL_DIR/$PLIST_NAME"
    
    # Wait a moment for service to start
    sleep 3
    
    # Check if service is running
    if launchctl list | grep -q "$SERVICE_NAME"; then
        log_success "File Transfer Agent service loaded successfully"
        
        # Show service status
        log_info "Service status:"
        launchctl list | grep "$SERVICE_NAME" || log_warning "Service not found in process list"
        
        # Test if web interface is responding
        sleep 5
        if curl -s http://localhost:8000/health > /dev/null; then
            log_success "Web interface is responding at http://localhost:8000"
        else
            log_warning "Web interface not responding yet, check logs"
        fi
    else
        log_error "Failed to load service"
        exit 1
    fi
}

# Create uninstall script
create_uninstall_script() {
    UNINSTALL_SCRIPT="$PROJECT_DIR/scripts/service-setup/uninstall-macos.sh"
    
    cat > "$UNINSTALL_SCRIPT" << 'EOF'
#!/bin/bash
# File Transfer Agent - macOS Uninstall Script

SERVICE_NAME="com.fileagent.service"
PLIST_NAME="${SERVICE_NAME}.plist"

if [[ $EUID -eq 0 ]]; then
    SERVICE_DIR="/Library/LaunchDaemons"
else
    SERVICE_DIR="$HOME/Library/LaunchAgents"
fi

echo "Uninstalling File Transfer Agent service..."

# Stop and unload service
if launchctl list | grep -q "$SERVICE_NAME"; then
    echo "Stopping service..."
    launchctl unload "$SERVICE_DIR/$PLIST_NAME"
fi

# Remove plist file
if [[ -f "$SERVICE_DIR/$PLIST_NAME" ]]; then
    echo "Removing service file..."
    rm -f "$SERVICE_DIR/$PLIST_NAME"
fi

echo "File Transfer Agent service uninstalled successfully"
echo "Note: Virtual environment and project files were not removed"
EOF

    chmod +x "$UNINSTALL_SCRIPT"
    log_success "Uninstall script created: $UNINSTALL_SCRIPT"
}

# Show status and next steps
show_completion_info() {
    log_success "🎉 File Transfer Agent macOS service setup complete!"
    echo
    log_info "Service Details:"
    echo "  • Service Name: $SERVICE_NAME"
    echo "  • Install Location: $INSTALL_DIR/$PLIST_NAME"
    echo "  • Working Directory: $PROJECT_DIR"
    echo "  • Log Files: $PROJECT_DIR/logs/"
    echo
    log_info "Service Management Commands:"
    echo "  • View Status: launchctl list | grep $SERVICE_NAME"
    echo "  • Stop Service: launchctl unload $INSTALL_DIR/$PLIST_NAME"
    echo "  • Start Service: launchctl load $INSTALL_DIR/$PLIST_NAME"
    echo "  • View Logs: tail -f $PROJECT_DIR/logs/file-agent.log"
    echo
    log_info "Web Interface:"
    echo "  • URL: http://localhost:8000"
    echo "  • Health Check: http://localhost:8000/health"
    echo "  • API Documentation: http://localhost:8000/docs"
    echo
    log_info "To uninstall:"
    echo "  • Run: $PROJECT_DIR/scripts/service-setup/uninstall-macos.sh"
}

# Main installation process
main() {
    echo "🚀 File Transfer Agent - macOS Service Setup"
    echo "============================================="
    echo
    
    check_permissions
    check_prerequisites
    
    # Create install directory if it doesn't exist
    mkdir -p "$INSTALL_DIR"
    
    create_plist_file
    load_service
    create_uninstall_script
    show_completion_info
}

# Handle Ctrl+C gracefully
trap 'log_error "Installation interrupted"; exit 1' INT

# Run main function
main "$@"