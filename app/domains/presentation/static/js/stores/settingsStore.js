// @ts-check



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

        // System info (build time, app dir)
        settingsData: null,
        settingsLoading: false,
        settingsError: null,

        // User-editable settings form
        editForm: {},
        isDirty: false,
        saving: false,
        saveMessage: null,
        saveSuccess: false,
        pendingRestart: false,

        // Administrative actions
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
            await this.loadUserSettings();
        },
        closeSettingsModal() {
            if (this.isDirty && !confirm('You have unsaved changes. Discard them?')) {
                return;
            }
            this.isDirty = false;
            this.showSettingsModal = false;
        },
        async loadSettings() {
            if (this.settingsLoading) return;
            this.settingsLoading = true;
            this.settingsError = null;
            try {
                const response = await fetch('/api/system/settings');
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                this.settingsData = await response.json();
                this.settingsError = null;
            } catch (error) {
                console.error('❌ Failed to load settings:', error);
                this.settingsError = error instanceof Error ? error.message : String(error);
                this.settingsData = null;
            } finally {
                this.settingsLoading = false;
            }
        },

        async loadUserSettings() {
            try {
                const response = await fetch('/api/system/user-settings');
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                const data = await response.json();
                const form = {};
                for (const s of data.settings) {
                    form[s.key] = s.value;
                }
                this.editForm = form;
                this.isDirty = false;
            } catch (error) {
                console.error('❌ Failed to load user settings:', error);
                this.settingsError = error instanceof Error ? error.message : String(error);
            }
        },

        markDirty() {
            this.isDirty = true;
        },

        async saveUserSettings() {
            if (!this.isDirty || this.saving) return;
            this.saving = true;
            this.saveMessage = null;
            try {
                const response = await fetch('/api/system/user-settings', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.editForm),
                });
                const result = await response.json();
                if (result.success) {
                    this.saveSuccess = true;
                    const changedCount = result.changed?.length || 0;
                    this.saveMessage = changedCount > 0
                        ? `Saved ${changedCount} setting(s) successfully.`
                        : 'No changes to save.';
                    this.isDirty = false;

                    if (result.requires_restart?.length > 0) {
                        this.pendingRestart = true;
                        this.saveMessage += ' Restart required for some changes.';
                    }

                    // Update editForm with returned values
                    if (result.settings) {
                        const form = {};
                        for (const s of result.settings) {
                            form[s.key] = s.value;
                        }
                        this.editForm = form;
                    }
                } else {
                    this.saveSuccess = false;
                    this.saveMessage = result.detail || result.message || 'Failed to save settings';
                }
            } catch (error) {
                console.error('❌ Failed to save settings:', error);
                this.saveSuccess = false;
                this.saveMessage = 'Network error: ' + (error instanceof Error ? error.message : String(error));
            } finally {
                this.saving = false;
                setTimeout(() => { this.saveMessage = null; }, 8000);
            }
        },

        /** @param {string} message */
        showErrorMessage(message) {
            console.error('Settings Error:', message);
            alert('Error: ' + message);
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
