#!/bin/bash
# File Transfer Agent - macOS Uninstall Script
#
# Usage:
#   chmod +x uninstall-macos.sh
#   ./uninstall-macos.sh          # Uninstall user service
#   sudo ./uninstall-macos.sh     # Uninstall system service

echo "🚀 Starting comprehensive uninstall of File Transfer Agent services..."

# --- Configuration ---
SERVICE_NAME="com.fileagent.service"
MAIN_PLIST_NAME="${SERVICE_NAME}.plist"
BROWSER_PLIST_NAME="com.fileagent.openbrowser.plist"
RESTART_SCRIPT_NAME="restart-fileagent.sh"

SYSTEM_SERVICE_DIR="/Library/LaunchDaemons"
USER_SERVICE_DIR="$HOME/Library/LaunchAgents"
USER_DESKTOP_DIR="$HOME/Desktop"

# --- Helper Functions ---
log_info() {
    echo -e "\033[0;34m[INFO]\033[0m $1"
}

log_success() {
    echo -e "\033[0;32m[SUCCESS]\033[0m $1"
}

log_warning() {
    echo -e "\033[1;33m[WARNING]\033[0m $1"
}

log_error() {
    echo -e "\033[0;31m[ERROR]\033[0m $1"
}

# --- Uninstall Main Service ---
uninstall_main_service() {
    log_info "Attempting to uninstall main service ($MAIN_PLIST_NAME)..."
    
    local service_plist_path=""

    # Check if system-wide service exists
    if [[ -f "$SYSTEM_SERVICE_DIR/$MAIN_PLIST_NAME" ]]; then
        service_plist_path="$SYSTEM_SERVICE_DIR/$MAIN_PLIST_NAME"
        log_info "Main service found in system-wide LaunchDaemons."
    # Check if user-specific service exists
    elif [[ -f "$USER_SERVICE_DIR/$MAIN_PLIST_NAME" ]]; then
        service_plist_path="$USER_SERVICE_DIR/$MAIN_PLIST_NAME"
        log_info "Main service found in user's LaunchAgents."
    else
        log_warning "Main service ($MAIN_PLIST_NAME) not found. Skipping."
        return 0
    fi

    # Unload service
    if launchctl list | grep -q "$SERVICE_NAME"; then
        log_info "Unloading main service..."
        launchctl unload "$service_plist_path" 2>/dev/null || true
        log_success "Main service unloaded."
    else
        log_info "Main service not currently loaded."
    fi

    # Remove plist file
    if [[ -f "$service_plist_path" ]]; then
        log_info "Removing main service plist file: $service_plist_path"
        rm -f "$service_plist_path"
        log_success "Main service plist file removed."
    fi
}

# --- Uninstall Browser Launch Agent ---
uninstall_browser_agent() {
    log_info "Attempting to uninstall browser launch agent ($BROWSER_PLIST_NAME)..."
    local browser_plist_path="$USER_SERVICE_DIR/$BROWSER_PLIST_NAME"

    if [[ ! -f "$browser_plist_path" ]]; then
        log_warning "Browser launch agent ($BROWSER_PLIST_NAME) not found. Skipping."
        return 0
    fi

    # Unload agent
    if launchctl list | grep -q "${BROWSER_PLIST_NAME%.*}"; then
        log_info "Unloading browser launch agent..."
        launchctl unload "$browser_plist_path" 2>/dev/null || true
        log_success "Browser launch agent unloaded."
    else
        log_info "Browser launch agent not currently loaded."
    fi

    # Remove plist file
    log_info "Removing browser launch agent plist file: $browser_plist_path"
    rm -f "$browser_plist_path"
    log_success "Browser launch agent plist file removed."
}

# --- Remove Restart Script from Desktop ---
remove_restart_script() {
    log_info "Attempting to remove restart script from Desktop..."
    local restart_script_path="$USER_DESKTOP_DIR/$RESTART_SCRIPT_NAME"

    if [[ -f "$restart_script_path" ]]; then
        log_info "Removing restart script: $restart_script_path"
        rm -f "$restart_script_path"
        log_success "Restart script removed from Desktop."
    else
        log_warning "Restart script ($RESTART_SCRIPT_NAME) not found on Desktop. Skipping."
    fi
}

# --- Main Uninstall Process ---
main() {
    uninstall_main_service
    uninstall_browser_agent
    remove_restart_script
    
    log_success "✅ Comprehensive uninstall complete. Project files were not removed."
}

# --- Execute Main ---
main "$@"
