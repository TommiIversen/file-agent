/**
 * UI Store for File Transfer Agent
 * 
 * Manages UI state including modals and settings data
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('ui', {
        // Modal states
        showSettingsModal: false,
        showLogViewerModal: false,
        
    // Settings modal state is now handled in settingsStore.js
        
    // Log viewer state is now handled in logViewerStore.js
        
        /**
         * Initialize the UI store
         */
        init() {
            console.log('🖥️ UI Store initialized');
        },
        
        // Settings modal open/close now handled in settingsStore.js
        
        // Log viewer modal open/close now handled in logViewerStore.js
        
        // Settings modal logic is now handled in settingsStore.js
        


    });
});

// Global functions for use in HTML
// Settings modal global functions are now in settingsStore.js

// Log viewer global functions are now in logViewerStore.js