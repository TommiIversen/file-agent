/**
 * UI Store for File Transfer Agent
 * 
 * Manages UI state including modals and settings data
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('ui', {
        // Modal states
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
        
        /**
         * Initialize the UI store
         */
        init() {
            console.log('🖥️ UI Store initialized');
        },
        
        /**
         * Open settings modal and load settings data
         */
        async openSettingsModal() {
            this.showSettingsModal = true;
            await this.loadSettings();
        },
        
        /**
         * Close settings modal
         */
        closeSettingsModal() {
            this.showSettingsModal = false;
        },
        
        /**
         * Load settings data from API
         */
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
        
        /**
         * Show error message to user
         */
        showErrorMessage(message) {
            // Simple error display - can be enhanced later
            console.error('UI Error:', message);
            alert('Error: ' + message);
        },
        
        /**
         * Reload configuration from file
         */
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
                    
                    // Automatically reload settings to show new values
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
                
                // Clear message after 5 seconds
                setTimeout(() => {
                    this.actionMessage = null;
                }, 5000);
            }
        },
        
        /**
         * Restart the entire application
         */
        async restartApplication() {
            if (this.restartingApp) return;
            
            // Confirm with user
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
                    
                    // Start countdown
                    const countdownInterval = setInterval(() => {
                        this.restartCountdown--;
                        if (this.restartCountdown <= 0) {
                            clearInterval(countdownInterval);
                            
                            // Show reconnecting message and try to reconnect
                            this.actionMessage = 'Application restarting... Reconnecting...';
                            
                            // Try to reconnect after restart
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
                
                // Clear message after 5 seconds
                setTimeout(() => {
                    this.actionMessage = null;
                }, 5000);
            }
        }
    });
});

// Global functions for use in HTML
window.openSettingsModal = function() {
    Alpine.store('ui').openSettingsModal();
};

window.closeSettingsModal = function() {
    Alpine.store('ui').closeSettingsModal();
};

window.reloadConfig = function() {
    Alpine.store('ui').reloadConfig();
};

window.restartApplication = function() {
    Alpine.store('ui').restartApplication();
};