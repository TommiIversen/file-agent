#!/bin/bash
# File Transfer Agent - macOS Service Setup Script
# Simple setup for File Transfer Agent as a macOS launchd service
#
# Usage:
#   chmod +x install-macos.sh
#   ./install-macos.sh          # User service (recommended for desktop)
#   sudo ./install-macos.sh     # System service (for servers)

set -e  # Exit on any error

# Configuration
SERVICE_NAME="com.fileagent.service"
PLIST_NAME="${SERVICE_NAME}.plist"
SERVICE_DIR="/Library/LaunchDaemons"  # System-wide service
USER_SERVICE_DIR="$HOME/Library/LaunchAgents"  # User service
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
    
    if [[ $EUID -eq 0 ]]; then
        log_info "Konfigurerer macOS firewall..."
        
        FIREWALL_CMD="/usr/libexec/ApplicationFirewall/socketfilterfw"
        
        if ! $FIREWALL_CMD --listapps | grep -q "$PYTHON_PATH"; then
            log_info "Tilføjer $PYTHON_PATH til firewall..."
            $FIREWALL_CMD --add "$PYTHON_PATH"
        else
            log_info "$PYTHON_PATH er allerede i firewall-listen."
        fi
        
        log_info "Sikrer, at $PYTHON_PATH har tilladelse til indgående forbindelser..."
        $FIREWALL_CMD --unblockapp "$PYTHON_PATH"
        
        log_success "Firewall konfigureret til at tillade $PYTHON_PATH"
    else
        log_warning "Scriptet køres ikke som root."
        log_warning "Firewallen blev IKKE konfigureret automatisk."
        log_warning "Du skal muligvis manuelt 'Tillad' indgående forbindelser, når systemet spørger."
    fi
}

# Configure macOS system permissions for network mounting
configure_system_permissions() {
    log_info "Konfigurerer system-tilladelser til network mounting..."
    
    if [[ $EUID -eq 0 ]]; then
        log_info "Tilføjer service bruger til admin-gruppen for mount-rettigheder..."
        
        if ! dscl . -read /Users/fileagent &>/dev/null; then
            log_info "Opretter dedikeret 'fileagent' bruger til service..."
            
            LAST_UID=$(dscl . -list /Users UniqueID | awk '{print $2}' | sort -n | tail -1)
            NEW_UID=$((LAST_UID + 1))
            
            dscl . -create /Users/fileagent
            dscl . -create /Users/fileagent UserShell /bin/bash
            dscl . -create /Users/fileagent RealName "File Agent Service"
            dscl . -create /Users/fileagent UniqueID $NEW_UID
            dscl . -create /Users/fileagent PrimaryGroupID 20  # staff group
            dscl . -create /Users/fileagent NFSHomeDirectory /var/empty
            
            dscl . -append /Groups/admin GroupMembership fileagent
            dscl . -append /Groups/_developer GroupMembership fileagent
            
            log_success "Fileagent bruger oprettet med UID $NEW_UID"
            SERVICE_USER="fileagent"
        else
            log_info "Fileagent bruger findes allerede"
            SERVICE_USER="fileagent"
        fi
        
        log_warning "VIGTIGT: Du skal muligvis manuelt give tilladelser til:"
        log_warning "  • System Preferences > Security & Privacy > Privacy"
        log_warning "  • Full Disk Access: Tilføj Python eller din app"
        log_warning "  • Files and Folders: Tilføj Python adgang til netværksvolumes"
    else
        log_warning "Kører ikke som root - kan ikke konfigurere system-tilladelser"
        log_warning "For bedste network mount support, kør: sudo ./install-macos.sh"
        SERVICE_USER="$(whoami)"
    fi
}

# Create keychain entry for SMB credentials (optional)
configure_keychain() {
    log_info "Konfigurerer keychain til SMB credentials..."
    
    HOSTNAME=$(hostname | cut -d'.' -f1)
    HOST_SETTINGS_FILE="$PROJECT_DIR/${HOSTNAME}-settings.env"
    
    SETTINGS_FILE=""
    if [[ -f "$HOST_SETTINGS_FILE" ]]; then
        SETTINGS_FILE="$HOST_SETTINGS_FILE"
        log_info "Bruger host-specifik konfiguration: $HOST_SETTINGS_FILE"
    elif [[ -f "$PROJECT_DIR/settings.env" ]]; then
        SETTINGS_FILE="$PROJECT_DIR/settings.env"
        log_info "Bruger base konfiguration: settings.env"
    fi
    
    if [[ -n "$SETTINGS_FILE" ]]; then
        SMB_URL=$(grep -E "^NETWORK_SHARE_URL=" "$SETTINGS_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'")
        
        if [[ -z "$SMB_URL" ]]; then
            SMB_URL=$(grep -E "^SMB_SHARE_URL=" "$SETTINGS_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'")
        fi
        
        if [[ -n "$SMB_URL" ]]; then
            log_info "Fundet SMB konfiguration: $SMB_URL"
            
            SMB_HOST=$(echo "$SMB_URL" | sed -E 's|smb://[^@]*@([^/]*)/.*|\1|')
            SMB_USER=$(echo "$SMB_URL" | sed -E 's|smb://([^@]*)@.*|\1|')
            
            if [[ -n "$SMB_HOST" && -n "$SMB_USER" ]]; then
                log_info "SMB Host: $SMB_HOST, User: $SMB_USER"
                log_info "Du kan tilføje SMB password til keychain med:"
                log_info "  security add-internet-password -a \"$SMB_USER\" -s \"$SMB_HOST\" -P 445 -r \"smb \" -w"
                log_info "Dette vil tillade automatisk mount uden password prompts"
            else
                log_info "Kunne ikke ekstraktere SMB credentials fra URL"
            fi
        else
            log_info "Ingen SMB konfiguration fundet i settings"
            log_info "Konfigurer NETWORK_SHARE_URL i din settings fil for automatisk keychain setup"
        fi
    else
        log_info "Ingen settings filer fundet endnu"
        log_info "Host-specifik fil ($HOST_SETTINGS_FILE) oprettes automatisk ved første app-start"
        log_info "Kør derefter dette script igen for keychain konfiguration"
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
    
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is required but not installed"
        log_info "Please install Python 3.13+ from https://www.python.org/downloads/"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log_info "Found Python version: $PYTHON_VERSION"
    
    if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 13) else 1)" 2>/dev/null; then
        log_error "Python 3.13+ required, found $PYTHON_VERSION"
        log_info "Please upgrade Python to 3.13+ from https://www.python.org/downloads/"
        exit 1
    fi
    
    if ! python3 -m pip --version &> /dev/null; then
        log_error "pip is required but not available"
        log_info "Please install pip or reinstall Python with pip included"
        exit 1
    fi
    
    if [[ ! -d "$PROJECT_DIR" ]]; then
        log_error "Project directory not found: $PROJECT_DIR"
        exit 1
    fi
    
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
    
    python3 -m pip install -r requirements.txt
    
    log_success "Dependencies installed successfully"
}

# Create the launch daemon plist file
create_plist_file() {
    log_info "Creating launchd plist file..."
    
    PYTHON_PATH=$(which python3)
    WORK_DIR="$PROJECT_DIR"
    LOG_DIR="$PROJECT_DIR/logs"
    
    mkdir -p "$LOG_DIR"
    
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

    chmod 644 "$INSTALL_DIR/$PLIST_NAME"
    
    if [[ $EUID -eq 0 ]]; then
        chown root:wheel "$INSTALL_DIR/$PLIST_NAME"
    fi
    
    log_success "Plist file created: $INSTALL_DIR/$PLIST_NAME"
}

# Load the service
load_service() {
    log_info "Loading File Transfer Agent service..."
    
    if launchctl list | grep -q "$SERVICE_NAME"; then
        log_info "Service already loaded, unloading first..."
        launchctl unload "$INSTALL_DIR/$PLIST_NAME" 2>/dev/null || true
    fi
    
    launchctl load "$INSTALL_DIR/$PLIST_NAME"
    
    sleep 3
    
    if launchctl list | grep -q "$SERVICE_NAME"; then
        log_success "File Transfer Agent service loaded successfully"
        
        log_info "Service status:"
        launchctl list | grep "$SERVICE_NAME" || log_warning "Service not found in process list"
        
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

# Create browser launch agent to open web UI on login
create_browser_launch_agent() {
    log_info "Creating launch agent to open web UI on login..."
    PLIST_DIR="$HOME/Library/LaunchAgents"
    PLIST_FILE="$PLIST_DIR/com.fileagent.openbrowser.plist"

    mkdir -p "$PLIST_DIR"

    cat > "$PLIST_FILE" << EOL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.fileagent.openbrowser</string>
    <key>ProgramArguments</key>
    <array>
        <string>open</string>
        <string>http://localhost:8000</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOL

    log_success "Launch agent created: $PLIST_FILE"
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
    echo "  • Run: $PROJECT_DIR/uninstall-macos.sh"
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
    configure_system_permissions
    configure_keychain
    
    mkdir -p "$INSTALL_DIR"
    
    create_plist_file
    load_service
    create_browser_launch_agent
    show_completion_info
}

# Handle Ctrl+C gracefully
trap 'log_error "Installation interrupted"; exit 1' INT

# Run main function
main "$@"
