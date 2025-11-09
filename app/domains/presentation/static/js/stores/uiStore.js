// @ts-check



/**
 * UI Store for File Transfer Agent
 *
 * Manages UI state including modals and settings data
 */
document.addEventListener('alpine:init', () => {
    /** @type {UIStore} */
    const uiStore = {
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

        /**
         * @param {Partial<ScannerStatus>} scannerData
         */
        updateScannerStatus(scannerData) {
            this.scanner = {
                scanning: scannerData.scanning || false,
                paused: scannerData.paused || false
            };
            console.log('🔍 Scanner status updated:', this.scanner);
        },
    };
    // @ts-ignore
    Alpine.store('ui', uiStore);
});