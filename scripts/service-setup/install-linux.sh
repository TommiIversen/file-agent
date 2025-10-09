#!/bin/bash
# File Transfer Agent - Linux systemd Service Setup Script
# This script sets up the File Transfer Agent as a Linux systemd service

set -e  # Exit on any error

# Configuration
SERVICE_NAME="file-transfer-agent"
SERVICE_FILE="${SERVICE_NAME}.service"
SYSTEMD_DIR="/etc/systemd/system"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
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
        INSTALL_DIR="$SYSTEMD_DIR"
        SERVICE_USER="fileagent"
        USE_SYSTEMCTL="systemctl"
    else
        log_info "Running as user - will install user service"
        INSTALL_DIR="$USER_SYSTEMD_DIR"
        SERVICE_USER="$(whoami)"
        USE_SYSTEMCTL="systemctl --user"
    fi
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check systemd
    if ! command -v systemctl &> /dev/null; then
        log_error "systemd is required but not found"
        exit 1
    fi
    
    # Check Python 3.8+
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is required but not installed"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log_info "Found Python version: $PYTHON_VERSION"
    
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

# Create system user for service (if running as root)
create_service_user() {
    if [[ $EUID -eq 0 ]] && ! id "$SERVICE_USER" &>/dev/null; then
        log_info "Creating service user: $SERVICE_USER"
        useradd --system --no-create-home --shell /bin/false "$SERVICE_USER"
        
        # Set ownership of project directory
        chown -R "$SERVICE_USER:$SERVICE_USER" "$PROJECT_DIR"
        log_success "Service user created: $SERVICE_USER"
    fi
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
    
    # Set proper ownership if running as root
    if [[ $EUID -eq 0 ]]; then
        chown -R "$SERVICE_USER:$SERVICE_USER" "$PROJECT_DIR/venv"
    fi
    
    log_success "Virtual environment created and dependencies installed"
}

# Create the systemd service file
create_service_file() {
    log_info "Creating systemd service file..."
    
    PYTHON_PATH="$PROJECT_DIR/venv/bin/python"
    WORK_DIR="$PROJECT_DIR"
    LOG_DIR="$PROJECT_DIR/logs"
    
    # Create logs directory
    mkdir -p "$LOG_DIR"
    
    # Set ownership if running as root
    if [[ $EUID -eq 0 ]]; then
        chown -R "$SERVICE_USER:$SERVICE_USER" "$LOG_DIR"
    fi
    
    # Create install directory if needed
    mkdir -p "$INSTALL_DIR"
    
    # Create the service file content
    cat > "$INSTALL_DIR/$SERVICE_FILE" << EOF
[Unit]
Description=File Transfer Agent - Automated video file transfer service
Documentation=https://github.com/TommiIversen/file-agent
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=exec
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$WORK_DIR
Environment=PATH=$PROJECT_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=$PROJECT_DIR
ExecStart=$PYTHON_PATH -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info
ExecReload=/bin/kill -HUP \$MAINPID

# Restart policy
Restart=always
RestartSec=30
TimeoutStartSec=60
TimeoutStopSec=30

# Security settings
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$PROJECT_DIR
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true

# Resource limits
LimitNOFILE=65536
MemoryMax=1G

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=file-transfer-agent

[Install]
WantedBy=multi-user.target
EOF

    # Set proper permissions
    chmod 644 "$INSTALL_DIR/$SERVICE_FILE"
    
    if [[ $EUID -eq 0 ]]; then
        chown root:root "$INSTALL_DIR/$SERVICE_FILE"
    fi
    
    log_success "Service file created: $INSTALL_DIR/$SERVICE_FILE"
}

# Enable and start the service
start_service() {
    log_info "Enabling and starting File Transfer Agent service..."
    
    # Reload systemd
    if [[ $EUID -eq 0 ]]; then
        systemctl daemon-reload
    else
        systemctl --user daemon-reload
    fi
    
    # Enable service (start on boot)
    $USE_SYSTEMCTL enable "$SERVICE_NAME"
    
    # Start service
    $USE_SYSTEMCTL start "$SERVICE_NAME"
    
    # Wait a moment for service to start
    sleep 3
    
    # Check service status
    if $USE_SYSTEMCTL is-active --quiet "$SERVICE_NAME"; then
        log_success "File Transfer Agent service started successfully"
        
        # Show service status
        log_info "Service status:"
        $USE_SYSTEMCTL status "$SERVICE_NAME" --no-pager -l
        
        # Test if web interface is responding
        sleep 5
        if curl -s http://localhost:8000/health > /dev/null; then
            log_success "Web interface is responding at http://localhost:8000"
        else
            log_warning "Web interface not responding yet, check logs"
        fi
    else
        log_error "Failed to start service"
        $USE_SYSTEMCTL status "$SERVICE_NAME" --no-pager -l
        exit 1
    fi
}

# Create uninstall script
create_uninstall_script() {
    UNINSTALL_SCRIPT="$PROJECT_DIR/scripts/service-setup/uninstall-linux.sh"
    
    cat > "$UNINSTALL_SCRIPT" << 'EOF'
#!/bin/bash
# File Transfer Agent - Linux Uninstall Script

SERVICE_NAME="file-transfer-agent"
SERVICE_FILE="${SERVICE_NAME}.service"

if [[ $EUID -eq 0 ]]; then
    SYSTEMD_DIR="/etc/systemd/system"
    USE_SYSTEMCTL="systemctl"
else
    SYSTEMD_DIR="$HOME/.config/systemd/user"
    USE_SYSTEMCTL="systemctl --user"
fi

echo "Uninstalling File Transfer Agent service..."

# Stop and disable service
if $USE_SYSTEMCTL is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "Stopping and disabling service..."
    $USE_SYSTEMCTL stop "$SERVICE_NAME"
    $USE_SYSTEMCTL disable "$SERVICE_NAME"
fi

# Remove service file
if [[ -f "$SYSTEMD_DIR/$SERVICE_FILE" ]]; then
    echo "Removing service file..."
    rm -f "$SYSTEMD_DIR/$SERVICE_FILE"
fi

# Reload systemd
if [[ $EUID -eq 0 ]]; then
    systemctl daemon-reload
else
    systemctl --user daemon-reload
fi

echo "File Transfer Agent service uninstalled successfully"
echo "Note: Virtual environment and project files were not removed"
EOF

    chmod +x "$UNINSTALL_SCRIPT"
    log_success "Uninstall script created: $UNINSTALL_SCRIPT"
}

# Show status and next steps
show_completion_info() {
    log_success "🎉 File Transfer Agent Linux service setup complete!"
    echo
    log_info "Service Details:"
    echo "  • Service Name: $SERVICE_NAME"
    echo "  • Service File: $INSTALL_DIR/$SERVICE_FILE"
    echo "  • Working Directory: $PROJECT_DIR"
    echo "  • User: $SERVICE_USER"
    echo
    log_info "Service Management Commands:"
    echo "  • View Status: $USE_SYSTEMCTL status $SERVICE_NAME"
    echo "  • Stop Service: $USE_SYSTEMCTL stop $SERVICE_NAME"
    echo "  • Start Service: $USE_SYSTEMCTL start $SERVICE_NAME"
    echo "  • Restart Service: $USE_SYSTEMCTL restart $SERVICE_NAME"
    echo "  • View Logs: journalctl -u $SERVICE_NAME -f"
    echo
    log_info "Web Interface:"
    echo "  • URL: http://localhost:8000"
    echo "  • Health Check: http://localhost:8000/health"
    echo "  • API Documentation: http://localhost:8000/docs"
    echo
    log_info "To uninstall:"
    echo "  • Run: $PROJECT_DIR/scripts/service-setup/uninstall-linux.sh"
}

# Main installation process
main() {
    echo "🚀 File Transfer Agent - Linux systemd Service Setup"
    echo "===================================================="
    echo
    
    check_permissions
    check_prerequisites
    
    if [[ $EUID -eq 0 ]]; then
        create_service_user
    fi
    
    create_service_file
    start_service
    create_uninstall_script
    show_completion_info
}

# Handle Ctrl+C gracefully
trap 'log_error "Installation interrupted"; exit 1' INT

# Run main function
main "$@"