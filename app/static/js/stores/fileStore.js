/**
 * File Store - File State Management
 *
 * Centralized state for file tracking, statistics, sorting,
 * and file lifecycle management with Alpine.js store pattern.
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('files', {
        // Configuration
        MAX_FILES: 400, // Maximum number of files to keep in the store

        // File State
        items: new Map(),               // Map<fileId, TrackedFile> - bruger ID i stedet for path!
        sortBy: 'discovered',          // Current sort method

        // Statistics State
        statistics: {
            totalFiles: 0,
            activeFiles: 0,
            completedFiles: 0,
            failedFiles: 0,
            growingFiles: 0
        },

        // File Management Actions
        addFile(file) {
            if (!file || !file.id) {
                console.error('addFile called with invalid file object:', file);
                return;
            }
            
            this.items.set(file.id, file);  // Brug ID som key

            if (this.items.size > this.MAX_FILES) {
                // Get the first (oldest) key in the Map
                const oldestFileId = this.items.keys().next().value;
                if (oldestFileId) {
                    this.items.delete(oldestFileId);
                    console.log(`Removed oldest file (ID: ${oldestFileId}) to maintain limit of ${this.MAX_FILES}`);
                }
            }

            this.updateStatisticsFromFiles();
            console.log(`File added: ${file.file_path} (ID: ${file.id})`);
        },

        updateFile(fileId, partialFile) {
            if (!fileId || !partialFile) {
                console.error('updateFile called with invalid parameters:', { fileId, partialFile });
                return;
            }
            
            if (this.items.has(fileId)) {
                const existingFile = this.items.get(fileId);
                // Merge the new properties into the existing file object
                Object.assign(existingFile, partialFile);
                
                // If the status is changing, log it
                if (partialFile.status) {
                    console.log(`File updated: ${existingFile.file_path} (ID: ${fileId}) - Status: ${partialFile.status}`);
                }

                // We might still want to update statistics if the status changed
                if (partialFile.status) {
                    this.updateStatisticsFromFiles();
                }

            } else {
                // If it's a full file object, add it. Otherwise, ignore.
                if (partialFile.id && partialFile.file_path) {
                    console.log(`Auto-adding unknown file during update: ${partialFile.file_path} (ID: ${fileId})`);
                    this.addFile(partialFile);
                } else {
                    console.warn(`Ignoring partial update for unknown file: ${fileId}`);
                }
            }
        },

        // Initial State Management
        setInitialFiles(files) {
            if (!Array.isArray(files)) {
                console.error('setInitialFiles called with non-array:', files);
                return;
            }
            
            console.log('Setting initial files:', files.length);
            this.items.clear();

            files.forEach(file => {
                if (file && file.id) {
                    this.items.set(file.id, file);  // Brug ID som key
                } else {
                    console.warn('Skipping invalid file in setInitialFiles:', file);
                }
            });

            this.updateStatisticsFromFiles();
        },

        // Sorting Management
        setSortBy(sortMethod) {
            this.sortBy = sortMethod;
            console.log(`Sort method changed to: ${sortMethod}`);
        },

        // Statistics Management
        updateStatistics(stats) {
            if (stats) {
                this.statistics.totalFiles = stats.total_files || 0;
                this.statistics.activeFiles = stats.active_files || 0;
                this.statistics.completedFiles = stats.completed_files || 0;
                this.statistics.failedFiles = stats.failed_files || 0;
                this.statistics.growingFiles = stats.growing_files || 0;
            }
        },

        updateStatisticsFromFiles() {
            const stats = {
                total: this.items.size,
                active: 0,
                completed: 0,
                failed: 0,
                growing: 0
            };

            this.items.forEach(file => {
                // Check if it's a growing file
                if (['Growing', 'ReadyToStartGrowing', 'GrowingCopy'].includes(file.status)) {
                    stats.growing++;
                }

                switch (file.status) {
                    case 'Completed':
                        stats.completed++;
                        break;
                    case 'Failed':
                        stats.failed++;
                        break;
                    default:
                        stats.active++;
                }
            });

            this.statistics.totalFiles = stats.total;
            this.statistics.activeFiles = stats.active;
            this.statistics.completedFiles = stats.completed;
            this.statistics.failedFiles = stats.failed;
            this.statistics.growingFiles = stats.growing;
        },

        // Computed Properties - File Lists
        get allFiles() {
            if (!this.items) {
                console.warn('fileStore.items is not initialized yet');
                return [];
            }
            const files = Array.from(this.items.values());
            return this.sortFiles(files);
        },

        get activeFiles() {
            if (!this.items) {
                console.warn('fileStore.items is not initialized yet');
                return [];
            }
            const files = Array.from(this.items.values())
                .filter(file => !['Completed', 'Failed'].includes(file.status));
            return this.sortFiles(files);
        },

        get completedFiles() {
            if (!this.items) {
                console.warn('fileStore.items is not initialized yet');
                return [];
            }
            const files = Array.from(this.items.values())
                .filter(file => file.status === 'Completed');
            return this.sortFiles(files);
        },

        get growingFiles() {
            if (!this.items) {
                console.warn('fileStore.items is not initialized yet');
                return [];
            }
            const files = Array.from(this.items.values())
                .filter(file => ['Growing', 'ReadyToStartGrowing', 'GrowingCopy'].includes(file.status));
            return this.sortFiles(files);
        },

        get failedFiles() {
            if (!this.items) {
                console.warn('fileStore.items is not initialized yet');
                return [];
            }
            const files = Array.from(this.items.values())
                .filter(file => file.status === 'Failed');
            return this.sortFiles(files);
        },

        // Sorting Logic
        sortFiles(files) {
            if (!files || !Array.isArray(files)) {
                console.warn('sortFiles called with invalid files array:', files);
                return [];
            }
            
            return files.sort((a, b) => {
                // Defensive checks for file objects
                if (!a || !b) {
                    console.warn('sortFiles: null file object detected', { a, b });
                    return 0;
                }
                
                switch (this.sortBy) {
                    case 'activity':
                        // Sort by most relevant timestamp based on status
                        const getRelevantTime = (file) => {
                            if (file.completed_at) return new Date(file.completed_at);
                            if (file.started_copying_at) return new Date(file.started_copying_at);
                            return new Date(file.discovered_at || 0);
                        };
                        return getRelevantTime(b) - getRelevantTime(a);

                    case 'discovered':
                        const aDiscovered = new Date(a.discovered_at || 0);
                        const bDiscovered = new Date(b.discovered_at || 0);
                        return bDiscovered - aDiscovered;

                    case 'started':
                        const aStarted = a.started_copying_at ? new Date(a.started_copying_at) : new Date(0);
                        const bStarted = b.started_copying_at ? new Date(b.started_copying_at) : new Date(0);
                        return bStarted - aStarted;

                    case 'completed':
                        const aCompleted = a.completed_at ? new Date(a.completed_at) : new Date(0);
                        const bCompleted = b.completed_at ? new Date(b.completed_at) : new Date(0);
                        return bCompleted - aCompleted;

                    case 'filename':
                        const aName = a.file_path.split(/[\/]/).pop().toLowerCase();
                        const bName = b.file_path.split(/[\/]/).pop().toLowerCase();
                        return aName.localeCompare(bName);

                    case 'size':
                        return (b.file_size || 0) - (a.file_size || 0);

                    default:
                        return 0;
                }
            });
        },

    });
});
