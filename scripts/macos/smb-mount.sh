#!/bin/bash
# SMB Auto-Mount Script for macOS File Transfer Agent
# ==================================================
# Dette script sikrer at SMB shares er mounted før File Agent starter

set -euo pipefail

# Configuration
readonly SCRIPT_NAME="$(basename "$0")"
readonly CONFIG_FILE="$HOME/.file-agent/smb-config"

# Default values (can be overridden in config file)
NAS_HOST="${NAS_HOST:-nas.local}"
NAS_SHARE="${NAS_SHARE:-shared}"
NAS_USER="${NAS_USER:-file-agent}"
MOUNT_POINT="${MOUNT_POINT:-/Volumes/ProductionNAS}"
MOUNT_TIMEOUT="${MOUNT_TIMEOUT:-30}"
USE_KEYCHAIN="${USE_KEYCHAIN:-true}"

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Logging functions
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

# Load configuration if exists
load_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        log_info "Loading configuration from $CONFIG_FILE"
        # shellcheck source=/dev/null
        source "$CONFIG_FILE"
    else
        log_warning "No config file found at $CONFIG_FILE, using defaults"
    fi
}

# Create default configuration file
create_config() {
    local config_dir
    config_dir="$(dirname "$CONFIG_FILE")"
    
    mkdir -p "$config_dir"
    
    cat > "$CONFIG_FILE" << EOF
# SMB Mount Configuration for File Transfer Agent
# ==============================================

# NAS Connection Details
NAS_HOST="nas.local"
NAS_SHARE="shared"
NAS_USER="file-agent"

# Mount Configuration
MOUNT_POINT="/Volumes/ProductionNAS"
MOUNT_TIMEOUT="30"
USE_KEYCHAIN="true"

# Network Settings
SMB_PROTOCOL_VERSION="3.0"
SMB_OPTIONS="rw,auto,nobrowse"
EOF

    log_success "Created default config file at $CONFIG_FILE"
    log_info "Please edit the configuration and run the script again"
}

# Check if share is already mounted
is_mounted() {
    mount | grep -q "$MOUNT_POINT"
}

# Get SMB password from keychain or prompt
get_smb_password() {
    if [[ "$USE_KEYCHAIN" == "true" ]]; then
        log_info "Attempting to retrieve password from keychain"
        if security find-internet-password -a "$NAS_USER" -s "$NAS_HOST" -w 2>/dev/null; then
            return 0
        else
            log_warning "Password not found in keychain"
        fi
    fi
    
    log_info "Please enter SMB password for $NAS_USER@$NAS_HOST:"
    read -s -r password
    echo "$password"
}

# Store password in keychain
store_password_in_keychain() {
    local password="$1"
    
    log_info "Storing password in keychain for future use"
    security add-internet-password \
        -a "$NAS_USER" \
        -s "$NAS_HOST" \
        -P 445 \
        -r "smb " \
        -w "$password" \
        -T /System/Library/CoreServices/NetAuthAgent.app \
        2>/dev/null || {
        log_warning "Could not store password in keychain (may already exist)"
    }
}

# Test SMB connection
test_smb_connection() {
    log_info "Testing SMB connection to $NAS_HOST"
    
    # Use smbutil to test connection
    if command -v smbutil >/dev/null 2>&1; then
        if timeout "$MOUNT_TIMEOUT" smbutil status "//$NAS_USER@$NAS_HOST/$NAS_SHARE" >/dev/null 2>&1; then
            log_success "SMB connection test successful"
            return 0
        else
            log_error "SMB connection test failed"
            return 1
        fi
    else
        log_warning "smbutil not available, skipping connection test"
        return 0
    fi
}

# Mount SMB share
mount_smb_share() {
    local password
    
    log_info "Mounting SMB share $NAS_HOST/$NAS_SHARE to $MOUNT_POINT"
    
    # Create mount point if it doesn't exist
    if [[ ! -d "$MOUNT_POINT" ]]; then
        log_info "Creating mount point directory: $MOUNT_POINT"
        sudo mkdir -p "$MOUNT_POINT"
    fi
    
    # Get password
    password=$(get_smb_password)
    
    # Mount the share
    if echo "$password" | sudo mount -t smbfs "//$NAS_USER@$NAS_HOST/$NAS_SHARE" "$MOUNT_POINT"; then
        log_success "Successfully mounted $NAS_HOST/$NAS_SHARE at $MOUNT_POINT"
        
        # Store password in keychain for future use
        if [[ "$USE_KEYCHAIN" == "true" ]]; then
            store_password_in_keychain "$password"
        fi
        
        return 0
    else
        log_error "Failed to mount SMB share"
        return 1
    fi
}

# Verify mount health
verify_mount_health() {
    log_info "Verifying mount health"
    
    # Check if directory is accessible
    if [[ ! -r "$MOUNT_POINT" ]]; then
        log_error "Mount point is not readable"
        return 1
    fi
    
    # Test directory listing
    if ! ls "$MOUNT_POINT" >/dev/null 2>&1; then
        log_error "Cannot list mount point contents"
        return 1
    fi
    
    # Test write access
    local test_file="$MOUNT_POINT/.smb_test_$$"
    if echo "test" > "$test_file" 2>/dev/null && rm "$test_file" 2>/dev/null; then
        log_success "Mount health verification passed"
        return 0
    else
        log_error "Mount point is not writable"
        return 1
    fi
}

# Unmount share
unmount_share() {
    if is_mounted; then
        log_info "Unmounting $MOUNT_POINT"
        if sudo umount "$MOUNT_POINT"; then
            log_success "Successfully unmounted $MOUNT_POINT"
        else
            log_error "Failed to unmount $MOUNT_POINT"
            return 1
        fi
    else
        log_info "Share is not currently mounted"
    fi
}

# Show current mount status
show_status() {
    echo
    echo "=== SMB Mount Status ==="
    echo "Host: $NAS_HOST"
    echo "Share: $NAS_SHARE" 
    echo "User: $NAS_USER"
    echo "Mount Point: $MOUNT_POINT"
    echo
    
    if is_mounted; then
        log_success "Share is currently MOUNTED"
        
        # Show mount details
        mount | grep "$MOUNT_POINT" | while read -r line; do
            echo "Mount details: $line"
        done
        
        # Show disk usage
        if command -v df >/dev/null 2>&1; then
            echo
            echo "Disk usage:"
            df -h "$MOUNT_POINT" 2>/dev/null || echo "Could not get disk usage"
        fi
    else
        log_warning "Share is currently NOT MOUNTED"
    fi
    echo
}

# Print usage information
usage() {
    cat << EOF
Usage: $SCRIPT_NAME [COMMAND]

SMB Auto-Mount Script for File Transfer Agent

Commands:
    mount      Mount the SMB share (default action)
    unmount    Unmount the SMB share
    status     Show current mount status
    test       Test SMB connection without mounting
    config     Create default configuration file
    help       Show this help message

Configuration:
    Config file: $CONFIG_FILE
    
    If config file doesn't exist, run:
    $SCRIPT_NAME config

Examples:
    $SCRIPT_NAME mount          # Mount SMB share
    $SCRIPT_NAME status         # Check if mounted
    $SCRIPT_NAME unmount        # Unmount share
    
For File Transfer Agent integration, add to your service startup:
    $0 mount && /path/to/file-agent
EOF
}

# Main execution
main() {
    local command="${1:-mount}"
    
    case "$command" in
        "mount")
            load_config
            
            if is_mounted; then
                log_success "SMB share is already mounted at $MOUNT_POINT"
                verify_mount_health
            else
                if test_smb_connection && mount_smb_share; then
                    verify_mount_health
                else
                    log_error "Failed to mount SMB share"
                    exit 1
                fi
            fi
            ;;
            
        "unmount")
            load_config
            unmount_share
            ;;
            
        "status")
            load_config
            show_status
            ;;
            
        "test")
            load_config
            test_smb_connection
            ;;
            
        "config")
            create_config
            ;;
            
        "help"|"--help"|"-h")
            usage
            ;;
            
        *)
            log_error "Unknown command: $command"
            echo
            usage
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"