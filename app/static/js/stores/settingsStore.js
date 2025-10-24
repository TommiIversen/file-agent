/**
 * Settings Modal Store for File Transfer Agent
 * Handles all state and actions related to the settings modal
 * Extracted for SRP and maintainability
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('settings', {
        // Modal state
        showSettingsModal: false,

        // Settings data
        settingsData: null,
        settingsLoading: false,
        settingsError: null,

        // Administrative actions
        reloadingConfig: false,
        restartingApp: false,
        restartCountdown: null,
        actionMessage: null,
        actionSuccess: false,

        init() {
            console.log('⚙️ Settings Store initialized');
        },

        async openSettingsModal() {
            this.showSettingsModal = true;
            await this.loadSettings();
        },
        closeSettingsModal() {
            this.showSettingsModal = false;
        },
        async loadSettings() {
            if (this.settingsLoading) return;
            this.settingsLoading = true;
            this.settingsError = null;
            try {
                console.log('📡 Loading settings from API...');
                const response = await fetch('/api/settings');
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                const settingsData = await response.json();
                this.settingsData = settingsData;
                this.settingsError = null;
                console.log('✅ Settings loaded successfully', settingsData);
            } catch (error) {
                console.error('❌ Failed to load settings:', error);
                this.settingsError = error.message;
                this.settingsData = null;
            } finally {
                this.settingsLoading = false;
            }
        },
        showErrorMessage(message) {
            console.error('Settings Error:', message);
            alert('Error: ' + message);
        },
        async reloadConfig() {
            if (this.reloadingConfig) return;
            this.reloadingConfig = true;
            this.actionMessage = null;
            try {
                console.log('🔄 Reloading configuration...');
                const response = await fetch('/api/reload-config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                const result = await response.json();
                if (result.success) {
                    this.actionSuccess = true;
                    this.actionMessage = result.message;
                    await this.loadSettings();
                    console.log('✅ Configuration reloaded successfully');
                } else {
                    this.actionSuccess = false;
                    this.actionMessage = result.message || 'Failed to reload configuration';
                    console.error('❌ Failed to reload configuration:', result.message);
                }
            } catch (error) {
                console.error('❌ Failed to reload configuration:', error);
                this.actionSuccess = false;
                this.actionMessage = 'Network error: ' + error.message;
            } finally {
                this.reloadingConfig = false;
                setTimeout(() => {
                    this.actionMessage = null;
                }, 5000);
            }
        },
        async restartApplication() {
            if (this.restartingApp) return;
            if (!confirm('Are you sure you want to restart the application? This will briefly interrupt file transfers.')) {
                return;
            }
            this.restartingApp = true;
            this.actionMessage = null;
            this.restartCountdown = 2;
            try {
                console.log('🚀 Restarting application...');
                const response = await fetch('/api/restart-application', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                const result = await response.json();
                if (result.success) {
                    this.actionSuccess = true;
                    this.actionMessage = result.message;
                    const countdownInterval = setInterval(() => {
                        this.restartCountdown--;
                        if (this.restartCountdown <= 0) {
                            clearInterval(countdownInterval);
                            this.actionMessage = 'Application restarting... Reconnecting...';
                            setTimeout(() => {
                                window.location.reload();
                            }, 3000);
                        }
                    }, 1000);
                    console.log('✅ Application restart initiated');
                } else {
                    this.actionSuccess = false;
                    this.actionMessage = result.message || 'Failed to restart application';
                    console.error('❌ Failed to restart application:', result.message);
                    this.restartingApp = false;
                }
            } catch (error) {
                console.error('❌ Failed to restart application:', error);
                this.actionSuccess = false;
                this.actionMessage = 'Network error: ' + error.message;
                this.restartingApp = false;
                setTimeout(() => {
                    this.actionMessage = null;
                }, 5000);
            }
        },

        async toggleScanner() {
            const uiStore = Alpine.store('ui');
            if (!uiStore) {
                console.error('UI store not available');
                return;
            }

            // Get current state from UI store (single source of truth)
            const isCurrentlyPaused = uiStore.scanner.paused;
            const endpoint = isCurrentlyPaused ? '/api/scanner/resume' : '/api/scanner/pause';
            const action = isCurrentlyPaused ? 'Resuming' : 'Pausing';
            
            this.actionMessage = null;
            
            try {
                console.log(`${action} scanner...`);
                
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                
                const result = await response.json();
                
                if (result.success) {
                    // WebSocket will automatically update uiStore - no manual sync needed
                    this.actionSuccess = true;
                    this.actionMessage = isCurrentlyPaused ? 'Scanner resumed successfully' : 'Scanner paused successfully';
                    console.log(`✅ Scanner ${isCurrentlyPaused ? 'resumed' : 'paused'} successfully`);
                } else {
                    this.actionSuccess = false;
                    this.actionMessage = `Failed to ${action.toLowerCase()} scanner`;
                    console.error(`❌ Failed to ${action.toLowerCase()} scanner`);
                }
            } catch (error) {
                console.error(`❌ Failed to toggle scanner:`, error);
                this.actionSuccess = false;
                this.actionMessage = 'Network error: ' + error.message;
            } finally {
                setTimeout(() => {
                    this.actionMessage = null;
                }, 5000);
            }
        }
    });
});

// Global functions for use in HTML (for settings modal only)
window.openSettingsModal = function() {
    Alpine.store('settings').openSettingsModal();
};
window.closeSettingsModal = function() {
    Alpine.store('settings').closeSettingsModal();
};
window.reloadConfig = function() {
    Alpine.store('settings').reloadConfig();
};
window.restartApplication = function() {
    Alpine.store('settings').restartApplication();
};
window.toggleScanner = function() {
    Alpine.store('settings').toggleScanner();
};
