/**
 * UI Store for File Transfer Agent
 * 
 * Manages UI state including modals and settings data
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('ui', {
        showSettingsModal: false,
        showLogViewerModal: false,
        
        // Scanner status
        scanner: {
            scanning: true,
            paused: false
        },

        init() {
            console.log('🖥️ UI Store initialized');
        },
        
        updateScannerStatus(scannerData) {
            this.scanner = {
                scanning: scannerData.scanning || false,
                paused: scannerData.paused || false
            };
            console.log('🔍 Scanner status updated:', this.scanner);
        },
    });
});
