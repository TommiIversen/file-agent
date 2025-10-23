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

        // Scanner control
        scannerPaused: false,
        scannerToggling: false,

        init() {
            console.log('⚙️ Settings Store initialized');
            this.loadScannerStatus();
        },

        async openSettingsModal() {
            this.showSettingsModal = true;
            await this.loadSettings();
            await this.loadScannerStatus(); // Reload scanner status when modal opens
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
        async loadScannerStatus() {
            try {
                console.log('📡 Loading scanner status...');
                const response = await fetch('/api/scanner/status');
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                const status = await response.json();
                this.scannerPaused = status.paused;
                
                // Update UI store with scanner status
                const uiStore = Alpine.store('ui');
                if (uiStore) {
                    uiStore.updateScannerStatus({
                        scanning: status.scanning || !status.paused,
                        paused: status.paused
                    });
                }
                
                console.log('✅ Scanner status loaded:', status);
            } catch (error) {
                console.error('❌ Failed to load scanner status:', error);
            }
        },
        async toggleScanner() {
            if (this.scannerToggling) return;
            this.scannerToggling = true;
            this.actionMessage = null;
            try {
                const endpoint = this.scannerPaused ? '/api/scanner/resume' : '/api/scanner/pause';
                const action = this.scannerPaused ? 'Resuming' : 'Pausing';
                console.log(`${action} scanner...`);
                
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                const result = await response.json();
                if (result.success) {
                    this.scannerPaused = result.paused;
                    
                    // Update UI store with new scanner status
                    const uiStore = Alpine.store('ui');
                    if (uiStore) {
                        uiStore.updateScannerStatus({
                            scanning: result.scanning || !result.paused,
                            paused: result.paused
                        });
                    }
                    
                    this.actionSuccess = true;
                    this.actionMessage = this.scannerPaused ? 'Scanner paused successfully' : 'Scanner resumed successfully';
                    console.log(`✅ Scanner ${this.scannerPaused ? 'paused' : 'resumed'} successfully`);
                } else {
                    this.actionSuccess = false;
                    this.actionMessage = `Failed to ${this.scannerPaused ? 'resume' : 'pause'} scanner`;
                    console.error(`❌ Failed to ${this.scannerPaused ? 'resume' : 'pause'} scanner`);
                }
            } catch (error) {
                console.error(`❌ Failed to toggle scanner:`, error);
                this.actionSuccess = false;
                this.actionMessage = 'Network error: ' + error.message;
            } finally {
                this.scannerToggling = false;
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
