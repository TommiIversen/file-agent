/**
 * UI Store for File Transfer Agent
 * 
 * Manages UI state including modals and settings data
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('ui', {
        showSettingsModal: false,
        showLogViewerModal: false,

        init() {
            console.log('🖥️ UI Store initialized');
        },
    });
});
