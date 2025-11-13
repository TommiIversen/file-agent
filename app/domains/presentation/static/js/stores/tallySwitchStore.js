// @ts-check

/**
 * @file Tally Switch Store - Alpine.js store for tally switch status
 *
 * Manages tally switch connectivity status and provides reactive state
 * for UI components that need to display tally switch online/offline status.
 */

document.addEventListener('alpine:init', () => {
    /** @type {TallySwitchStore} */
    const tallySwitchStore = {
        // === STATE ===
        
        /** @type {boolean|null} */
        isOnline: null, // null = unknown, true = online, false = offline
        
        /** @type {string} */
        switchType: 'unknown',
        
        /** @type {string} */
        ipAddress: 'unknown',
        
        /** @type {string|null} */
        lastChecked: null,
        
        /** @type {string|null} */
        errorMessage: null,
        
        /** @type {boolean} */
        isMonitoring: false,

        // === METHODS ===

        init() {
            console.log('🔴 Tally Switch Store initialized');
        },

        /**
         * @param {Object} statusData - Status data from WebSocket or API  
         */
        updateStatus(statusData) {
            const previousOnline = this.isOnline;
            
            // Cast to any to avoid TypeScript errors
            const data = /** @type {any} */ (statusData);
            
            this.isOnline = data.is_online;
            this.switchType = data.switch_type || 'unknown';
            this.ipAddress = data.ip_address || 'unknown';
            this.lastChecked = data.last_checked;
            this.errorMessage = data.error_message;
            this.isMonitoring = data.is_monitoring || false;

            // Log status changes
            if (previousOnline !== null && previousOnline !== this.isOnline) {
                if (this.isOnline) {
                    console.log(`🟢 Tally switch ${this.ipAddress} came ONLINE`);
                } else {
                    console.log(`🔴 Tally switch ${this.ipAddress} went OFFLINE`);
                }
            }

            console.log(`🔴 Tally switch status updated: ${this.ipAddress} - ${this.isOnline ? 'ONLINE' : 'OFFLINE'}`);
        },

        /**
         * Handle initial state data containing tally switch status
         * @param {InitialStateData} initialData - Initial state data
         */
        loadInitialData(initialData) {
            // Cast to any to avoid TypeScript errors
            const data = /** @type {any} */ (initialData);
            
            if (data.tally_switch) {
                console.log('🔴 Loading tally switch status from initial state');
                this.updateStatus(data.tally_switch);
            }
        },

        // === METHODS ===

        /**
         * Get the status color class for the tally switch indicator
         * @returns {string} Tailwind CSS color class
         */
        getStatusColor() {
            if (this.isOnline === null) {
                return 'bg-gray-500'; // Unknown status
            }
            return this.isOnline ? 'bg-green-500' : 'bg-red-500';
        },

        /**
         * Get human-readable status text
         * @returns {string} Status text for display
         */
        getIndicatorText() {
            if (this.isOnline === null) {
                return 'Tally: Unknown';
            }
            return this.isOnline ? 'Tally: Online' : 'Tally: Offline';
        },

        /**
         * Get tooltip text with detailed information
         * @returns {string} Detailed status for tooltip
         */
        getStatusTooltip() {
            const baseText = `Tally Switch (${this.ipAddress})`;
            const statusText = this.isOnline === null ? 'Status Unknown' : 
                             this.isOnline ? 'Online' : 'Offline';
            const timeText = this.lastChecked ? 
                           `\nLast checked: ${new Date(this.lastChecked).toLocaleString('da-DK')}` : 
                           '\nNot yet checked';
            const errorText = this.errorMessage ? `\nError: ${this.errorMessage}` : '';
            
            return `${baseText}\n${statusText}${timeText}${errorText}`;
        }
    };

    Alpine.store('tallySwitch', tallySwitchStore);
});