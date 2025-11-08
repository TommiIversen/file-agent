// @ts-check

/**
 * @typedef {object} SettingsData
 * @property {string} source_directory
 * @property {string} destination_directory
 * @property {boolean} output_folder_template_enabled
 * @property {string} output_folder_rules
 * @property {string} output_folder_default_category
 * @property {string} output_folder_date_format
 * @property {number} file_stable_time_seconds
 * @property {number} polling_interval_seconds
 * @property {boolean} use_temporary_file
 * @property {number} max_retry_attempts
 * @property {number} retry_delay_seconds
 * @property {number} global_retry_delay_seconds
 * @property {number} copy_progress_update_interval
 * @property {number} file_operation_timeout_seconds
 * @property {number} chunk_size_kb
 * @property {string} log_level
 * @property {string} log_file_path
 * @property {number} log_retention_days
 * @property {number} storage_check_interval_seconds
 * @property {number} source_warning_threshold_gb
 * @property {number} source_critical_threshold_gb
 * @property {number} destination_warning_threshold_gb
 * @property {number} destination_critical_threshold_gb
 * @property {string} storage_test_file_prefix
 * @property {boolean} enable_pre_copy_space_check
 * @property {number} copy_safety_margin_gb
 * @property {number} space_retry_delay_seconds
 * @property {number} max_space_retries
 * @property {number} minimum_free_space_after_copy_gb
 * @property {number} space_error_cooldown_minutes
 * @property {number} keep_files_hours
 * @property {number} growing_file_min_size_mb
 * @property {number} growing_file_safety_margin_mb
 * @property {number} growing_file_poll_interval_seconds
 * @property {number} growing_file_growth_timeout_seconds
 * @property {number} growing_file_chunk_size_kb
 * @property {number} growing_copy_pause_ms
 * @property {boolean} enable_secure_resume
 * @property {number} max_concurrent_copies
 * @property {boolean} enable_auto_mount
 * @property {string} network_share_url
 * @property {string} windows_drive_letter
 * @property {string} macos_mount_point
 * @property {string} justin_api_base_url
 * @property {number} justin_fast_poll_interval_seconds
 * @property {number} justin_slow_poll_interval_seconds
 * @property {number} justin_api_timeout_seconds
 * @property {string} tally_light_api_url
 * @property {number} tally_light_blink_interval_seconds
 * @property {number} tally_light_api_timeout_seconds
 */

/**
 * @typedef {object} SettingsStore
 * @property {boolean} showSettingsModal
 * @property {SettingsData | null} settingsData
 * @property {boolean} settingsLoading
 * @property {string | null} settingsError
 * @property {boolean} reloadingConfig
 * @property {boolean} restartingApp
 * @property {number | null} restartCountdown
 * @property {boolean} scannerToggling
 * @property {string | null} actionMessage
 * @property {boolean} actionSuccess
 * @property {() => void} init
 * @property {() => Promise<void>} openSettingsModal
 * @property {() => void} closeSettingsModal
 * @property {() => Promise<void>} loadSettings
 * @property {(message: string) => void} showErrorMessage
 * @property {() => Promise<void>} reloadConfig
 * @property {() => Promise<void>} restartApplication
 * @property {() => Promise<void>} toggleScanner
 */

/**
 * Settings Modal Store for File Transfer Agent
 * Handles all state and actions related to the settings modal
 * Extracted for SRP and maintainability
 */
document.addEventListener('alpine:init', () => {
    /** @type {SettingsStore} */
    const settingsStore = {
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
        scannerToggling: false,
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
                const response = await fetch('/api/system/settings');
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                /** @type {SettingsData} */
                const settingsData = await response.json();
                this.settingsData = settingsData;
                this.settingsError = null;
                console.log('✅ Settings loaded successfully', settingsData);
            } catch (error) {
                console.error('❌ Failed to load settings:', error);
                this.settingsError = error instanceof Error ? error.message : String(error);
                this.settingsData = null;
            } finally {
                this.settingsLoading = false;
            }
        },
        /** @param {string} message */
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
                const response = await fetch('/api/system/reload-config', {
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
                this.actionMessage = 'Network error: ' + (error instanceof Error ? error.message : String(error));
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
                const response = await fetch('/api/system/restart-application', {
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
                        if (this.restartCountdown) {
                            this.restartCountdown--;
                        }
                        if (this.restartCountdown !== null && this.restartCountdown <= 0) {
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
                this.actionMessage = 'Network error: ' + (error instanceof Error ? error.message : String(error));
                this.restartingApp = false;
                setTimeout(() => {
                    this.actionMessage = null;
                }, 5000);
            }
        },

        async toggleScanner() {
            if (this.scannerToggling) return;

            const uiStore = Alpine.store('ui');
            if (!uiStore) {
                console.error('UI store not available');
                return;
            }

            // Get current state from UI store (single source of truth)
            const isCurrentlyPaused = uiStore.scanner.paused;
            const endpoint = isCurrentlyPaused ? '/api/scanner/resume' : '/api/scanner/pause';
            const action = isCurrentlyPaused ? 'Resuming' : 'Pausing';

            this.scannerToggling = true;
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
                this.actionMessage = 'Network error: ' + (error instanceof Error ? error.message : String(error));
            } finally {
                this.scannerToggling = false;
                setTimeout(() => {
                    this.actionMessage = null;
                }, 5000);
            }
        }
    };
    Alpine.store('settings', settingsStore);
});

// Global functions for use in HTML (for settings modal only)
window.openSettingsModal = function () {
    Alpine.store('settings').openSettingsModal();
};
window.closeSettingsModal = function () {
    Alpine.store('settings').closeSettingsModal();
};
window.reloadConfig = function () {
    Alpine.store('settings').reloadConfig();
};
window.restartApplication = function () {
    Alpine.store('settings').restartApplication();
};
window.toggleScanner = function () {
    Alpine.store('settings').toggleScanner();
};