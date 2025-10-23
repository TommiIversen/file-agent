#!/bin/bash
# File Transfer Agent - macOS Service Setup Script
# Simple setup for File Transfer Agent as a macOS launchd service

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

# Configure macOS Application Firewall
configure_firewall() {
    PYTHON_PATH=$(which python3)
    
    # Tjek om vi kører som root
    if [[ $EUID -eq 0 ]]; then
        log_info "Konfigurerer macOS firewall..."
        
        # Stien til firewall-værktøjet
        FIREWALL_CMD="/usr/libexec/ApplicationFirewall/socketfilterfw"
        
        # 1. Tilføj applikationen til firewall-listen
        # Vi tjekker først, om den allerede er der
        if ! $FIREWALL_CMD --listapps | grep -q "$PYTHON_PATH"; then
            log_info "Tilføjer $PYTHON_PATH til firewall..."
            $FIREWALL_CMD --add "$PYTHON_PATH"
        else
            log_info "$PYTHON_PATH er allerede i firewall-listen."
        fi
        
        # 2. Sørg for at applikationen er sat til "Tillad"
        log_info "Sikrer, at $PYTHON_PATH har tilladelse til indgående forbindelser..."
        $FIREWALL_CMD --unblockapp "$PYTHON_PATH"
        
        log_success "Firewall konfigureret til at tillade $PYTHON_PATH"
        
    else
        log_warning "Scriptet køres ikke som root."
        log_warning "Firewallen blev IKKE konfigureret automatisk."
        log_warning "Du skal muligvis manuelt 'Tillad' indgående forbindelser, når systemet spørger."
    fi
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
    
    # Check Python 3.13+
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is required but not installed"
        log_info "Please install Python 3.13+ from https://www.python.org/downloads/"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log_info "Found Python version: $PYTHON_VERSION"
    
    # Check for Python 3.13+
    if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 13) else 1)" 2>/dev/null; then
        log_error "Python 3.13+ required, found $PYTHON_VERSION"
        log_info "Please upgrade Python to 3.13+ from https://www.python.org/downloads/"
        exit 1
    fi
    
    # Check if pip is available
    if ! python3 -m pip --version &> /dev/null; then
        log_error "pip is required but not available"
        log_info "Please install pip or reinstall Python with pip included"
        exit 1
    fi
    
    # Check if project directory exists
    if [[ ! -d "$PROJECT_DIR" ]]; then
        log_error "Project directory not found: $PROJECT_DIR"
        exit 1
    fi
    
    # Check if requirements.txt exists
    if [[ ! -f "$PROJECT_DIR/requirements.txt" ]]; then
        log_error "requirements.txt not found in project directory"
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

# Install dependencies
install_dependencies() {
    log_info "Installing dependencies..."
    cd "$PROJECT_DIR"
    
    # Install requirements
    python3 -m pip install -r requirements.txt
    
    log_success "Dependencies installed successfully"
}

# Test application startup
test_application() {
    log_info "Testing application startup..."
    cd "$PROJECT_DIR"
    
    # Test that the app can start
    timeout 10s python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8001 &
    APP_PID=$!
    
    # Wait a moment for startup
    sleep 5
    
    # Check if app is responding
    if curl -s http://localhost:8001/health > /dev/null 2>&1; then
        log_success "Application startup test successful"
        kill $APP_PID 2>/dev/null || true
    else
        log_warning "Application health check failed, but continuing with service setup"
        kill $APP_PID 2>/dev/null || true
    fi
    
    # Wait for cleanup
    sleep 2
}

# Create the launch daemon plist file
create_plist_file() {
    log_info "Creating launchd plist file..."
    
    PYTHON_PATH=$(which python3)
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

# Copy restart script to user's Desktop for convenience
if [[ -n "$HOME" && -f "$PROJECT_DIR/scripts/service-setup/restart-macos.sh" ]]; then
    cp "$PROJECT_DIR/scripts/service-setup/restart-macos.sh" "$HOME/Desktop/restart-fileagent.sh"
    chmod +x "$HOME/Desktop/restart-fileagent.sh"
    log_success "Restart script copied to your Desktop as restart-fileagent.sh"
fi

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
    echo "  • Restart Service: "
    echo "    launchctl unload $INSTALL_DIR/$PLIST_NAME"
    echo "    launchctl load $INSTALL_DIR/$PLIST_NAME"
    echo "  • View Logs: tail -f $PROJECT_DIR/logs/file-agent.log"
    echo "  • View Error Logs: tail -f $PROJECT_DIR/logs/file-agent-error.log"
    echo
    log_info "Web Interface:"
    echo "  • URL: http://localhost:8000"
    echo "  • Health Check: http://localhost:8000/health"
    echo "  • API Documentation: http://localhost:8000/docs"
    echo
    log_info "Manual Startup (for testing):"
    echo "  • cd $PROJECT_DIR"
    echo "  • python3 -m uvicorn app.main:app --reload"
    echo "  • or: python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
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
    install_dependencies
    configure_firewall

    test_application
    
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