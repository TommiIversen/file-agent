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
        
        // Log viewer data
        logFiles: [],
        loadingLogFiles: false,
        logFilesError: null,
        selectedLogFile: null,
        logContent: null,
        loadingLogContent: false,
        
        // Chunked loading data
        logChunks: [],
        currentChunkInfo: null,
        loadingChunk: false,
        chunkError: null,
        viewMode: 'full', // 'full' or 'chunked'
        
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
         * Open log viewer modal and load log files
         */
        async openLogViewerModal() {
            this.showLogViewerModal = true;
            await this.loadLogFiles();
        },
        
        /**
         * Close log viewer modal
         */
        closeLogViewerModal() {
            this.showLogViewerModal = false;
            this.selectedLogFile = null;
            this.logContent = null;
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
        },
        
        /**
         * Load available log files from API
         */
        async loadLogFiles() {
            if (this.loadingLogFiles) return;
            
            this.loadingLogFiles = true;
            this.logFilesError = null;
            
            try {
                console.log('📂 Loading log files...');
                
                const response = await fetch('/api/log-files');
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                const result = await response.json();
                
                if (result.success) {
                    this.logFiles = result.log_files || [];
                    console.log('✅ Log files loaded successfully', this.logFiles);
                } else {
                    this.logFilesError = result.message || 'Failed to load log files';
                    console.error('❌ Failed to load log files:', result.message);
                }
                
            } catch (error) {
                console.error('❌ Failed to load log files:', error);
                this.logFilesError = 'Network error: ' + error.message;
                
            } finally {
                this.loadingLogFiles = false;
            }
        },
        
        /**
         * Load content of a specific log file
         */
        async loadLogFile(logFile) {
            if (this.loadingLogContent) return;
            
            this.loadingLogContent = true;
            this.selectedLogFile = logFile;
            this.logContent = null;
            this.logChunks = [];
            this.currentChunkInfo = null;
            this.chunkError = null;
            
            // For large files (>5MB), use chunked loading by default
            const useLazyLoading = logFile.size_mb > 5;
            this.viewMode = useLazyLoading ? 'chunked' : 'full';
            
            try {
                console.log(`📄 Loading log file content: ${logFile.filename} (${this.viewMode} mode)`);
                
                if (this.viewMode === 'chunked') {
                    // Load just the first chunk for large files
                    await this.loadLogChunk(logFile.filename, 0, 'forward');
                } else {
                    // Load full content for smaller files
                    await this.loadFullLogContent(logFile);
                }
                
            } catch (error) {
                console.error('❌ Failed to load log file content:', error);
                this.logContent = `Error loading log file: ${error.message}`;
                
            } finally {
                this.loadingLogContent = false;
            }
        },
        
        /**
         * Load full log content (for smaller files)
         */
        async loadFullLogContent(logFile) {
            // Use the new API endpoint that handles active log files properly
            const response = await fetch(`/api/log-content/${encodeURIComponent(logFile.filename)}`);
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => null);
                throw new Error(errorData?.detail || `HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            if (!data.success) {
                throw new Error(data.message || 'Failed to load log content');
            }
            
            this.logContent = data.content;
            
            // Update the selected log file with fresh metadata
            this.selectedLogFile = {
                ...logFile,
                size_bytes: data.size_bytes,
                size_mb: data.size_mb,
                modified_time: data.modified_time,
                is_current: data.is_current,
                lines: data.lines
            };
            
            console.log('✅ Full log file content loaded successfully');
        },
        
        /**
         * Load a chunk of log content
         */
        async loadLogChunk(filename, offset = 0, direction = 'forward', limit = 1000) {
            if (this.loadingChunk) return;
            
            this.loadingChunk = true;
            this.chunkError = null;
            
            try {
                console.log(`📄 Loading log chunk: ${filename} (offset: ${offset}, direction: ${direction})`);
                
                const params = new URLSearchParams({
                    offset: offset.toString(),
                    limit: limit.toString(),
                    direction: direction
                });
                
                const response = await fetch(`/api/log-content/${encodeURIComponent(filename)}/chunk?${params}`);
                
                if (!response.ok) {
                    const errorData = await response.json().catch(() => null);
                    throw new Error(errorData?.detail || `HTTP ${response.status}: ${response.statusText}`);
                }
                
                const data = await response.json();
                
                if (!data.success) {
                    throw new Error(data.message || 'Failed to load log chunk');
                }
                
                // Update chunk info
                this.currentChunkInfo = data.chunk_info;
                
                // Update file info
                this.selectedLogFile = {
                    ...this.selectedLogFile,
                    filename: data.filename,
                    size_bytes: data.file_info.size_bytes,
                    size_mb: data.file_info.size_mb,
                    modified_time: data.file_info.modified_time,
                    is_current: data.file_info.is_current,
                    lines: data.chunk_info.total_lines
                };
                
                if (direction === 'forward' && offset === 0) {
                    // Initial load - replace chunks
                    this.logChunks = data.lines;
                } else if (direction === 'forward') {
                    // Load more forward - append
                    this.logChunks.push(...data.lines);
                } else {
                    // Load more backward - prepend
                    this.logChunks.unshift(...data.lines);
                }
                
                console.log(`✅ Log chunk loaded successfully (${data.lines.length} lines)`);
                
            } catch (error) {
                console.error('❌ Failed to load log chunk:', error);
                this.chunkError = error.message;
                
            } finally {
                this.loadingChunk = false;
            }
        },
        
        /**
         * Load more content forward (toward end of file)
         */
        async loadMoreForward() {
            if (!this.currentChunkInfo || !this.currentChunkInfo.has_more_forward) return;
            
            await this.loadLogChunk(
                this.selectedLogFile.filename,
                this.currentChunkInfo.next_forward_offset,
                'forward'
            );
        },
        
        /**
         * Load more content backward (toward beginning of file)
         */
        async loadMoreBackward() {
            if (!this.currentChunkInfo || !this.currentChunkInfo.has_more_backward) return;
            
            await this.loadLogChunk(
                this.selectedLogFile.filename,
                this.currentChunkInfo.next_backward_offset,
                'backward'
            );
        },
        
        /**
         * Download log file
         */
        async downloadLogFile(filename) {
            try {
                console.log(`💾 Downloading log file: ${filename}`);
                
                // Create a temporary link to trigger download
                const downloadUrl = `/api/log-download/${encodeURIComponent(filename)}`;
                const link = document.createElement('a');
                link.href = downloadUrl;
                link.download = filename;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                
                console.log('✅ Download started');
                
            } catch (error) {
                console.error('❌ Failed to download log file:', error);
                alert(`Failed to download log file: ${error.message}`);
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

window.openLogViewerModal = function() {
    Alpine.store('ui').openLogViewerModal();
};

window.closeLogViewerModal = function() {
    Alpine.store('ui').closeLogViewerModal();
};

window.loadLogFile = function(logFile) {
    Alpine.store('ui').loadLogFile(logFile);
};

window.loadMoreForward = function() {
    Alpine.store('ui').loadMoreForward();
};

window.loadMoreBackward = function() {
    Alpine.store('ui').loadMoreBackward();
};

window.downloadLogFile = function(filename) {
    Alpine.store('ui').downloadLogFile(filename);
};