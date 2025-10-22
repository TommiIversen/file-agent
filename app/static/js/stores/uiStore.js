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