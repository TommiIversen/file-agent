/**
 * Log Viewer Store for File Transfer Agent
 * Handles all state and actions related to the log viewer modal
 * Extracted for SRP and maintainability
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('logViewer', {
        // Modal state (optional, can be controlled from UI store)
        showLogViewerModal: false,

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

        init() {
            console.log('📝 LogViewer Store initialized');
        },

        async openLogViewerModal() {
            this.showLogViewerModal = true;
            await this.loadLogFiles();
        },
        closeLogViewerModal() {
            this.showLogViewerModal = false;
            this.selectedLogFile = null;
            this.logContent = null;
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

                const response = await fetch('/api/logs/');
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                const logFiles = await response.json();
                this.logFiles = logFiles || [];
                console.log('✅ Log files loaded successfully', this.logFiles);

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

            // For large files (>1MB), use chunked loading by default
            const useLazyLoading = logFile.size_mb > 1;
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
            const response = await fetch(`/api/logs/${encodeURIComponent(logFile.filename)}/content`);

            if (!response.ok) {
                const errorData = await response.json().catch(() => null);
                throw new Error(errorData?.detail || `HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            this.logContent = data.content;

            // Update the selected log file with fresh metadata
            this.selectedLogFile = {
                ...logFile,
                size_bytes: data.size,
                size_mb: (data.size / (1024 * 1024)).toFixed(2),
                lines: data.lines
            };

            console.log('✅ Full log file content loaded successfully');
        },

        async loadLogChunk(filename, start = 0, direction = 'forward', limit = 1000) {
            if (this.loadingChunk) return;

            this.loadingChunk = true;
            this.chunkError = null;

            try {
                console.log(`📄 Loading log chunk: ${filename} (start: ${start}, direction: ${direction})`);

                const params = new URLSearchParams({
                    start: start.toString(),
                    limit: limit.toString()
                });

                const response = await fetch(`/api/logs/${encodeURIComponent(filename)}/content/chunk?${params}`);

                if (!response.ok) {
                    const errorData = await response.json().catch(() => null);
                    throw new Error(errorData?.detail || `HTTP ${response.status}: ${response.statusText}`);
                }

                const data = await response.json();

                // Update chunk info - adapt to new API structure
                this.currentChunkInfo = {
                    has_more_forward: data.has_more,
                    has_more_backward: data.start > 0,
                    next_forward_offset: data.start + data.returned,
                    next_backward_offset: Math.max(0, data.start - limit),
                    total_lines: data.total_lines
                };

                // Update file info
                this.selectedLogFile = {
                    ...this.selectedLogFile,
                    lines: data.total_lines
                };

                // Parse content into lines
                const lines = data.content ? data.content.split('\n') : [];

                if (direction === 'forward' && start === 0) {
                    // Initial load - replace chunks
                    this.logChunks = lines;
                } else if (direction === 'forward') {
                    // Load more forward - append
                    this.logChunks.push(...lines);
                } else {
                    // Load more backward - prepend
                    this.logChunks.unshift(...lines);
                }

                console.log(`✅ Log chunk loaded successfully (${lines.length} lines)`);

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
                const downloadUrl = `/api/logs/${encodeURIComponent(filename)}/download`;
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

// Global functions for use in HTML (for log viewer only)
window.openLogViewerModal = function () {
    Alpine.store('logViewer').openLogViewerModal();
};
window.closeLogViewerModal = function () {
    Alpine.store('logViewer').closeLogViewerModal();
};
window.loadLogFile = function (logFile) {
    Alpine.store('logViewer').loadLogFile(logFile);
};
window.loadMoreForward = function () {
    Alpine.store('logViewer').loadMoreForward();
};
window.loadMoreBackward = function () {
    Alpine.store('logViewer').loadMoreBackward();
};
window.downloadLogFile = function (filename) {
    Alpine.store('logViewer').downloadLogFile(filename);
};
