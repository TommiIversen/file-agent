/**
 * File Store - File State Management
 *
 * Centralized state for file tracking, statistics, sorting,
 * and file lifecycle management with Alpine.js store pattern.
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('files', {
        // File State
        items: new Map(),               // Map<filePath, TrackedFile>
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
            this.items.set(file.file_path, file);
            this.updateStatisticsFromFiles();
            console.log(`File added: ${file.file_path}`);
        },

        updateFile(filePath, file) {
            if (this.items.has(filePath)) {
                this.items.set(filePath, file);
                this.updateStatisticsFromFiles();
                console.log(`File updated: ${filePath} - Status: ${file.status}`);
            } else {
                // File doesn't exist yet - add it automatically
                console.log(`Auto-adding unknown file during update: ${filePath}`);
                this.addFile(file);  // Send only the file object, not filePath
            }
        },

        // Initial State Management
        setInitialFiles(files) {
            console.log('Setting initial files:', files.length);
            this.items.clear();

            files.forEach(file => {
                this.items.set(file.file_path, file);
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
                if (file.is_growing_file || ['Growing', 'ReadyToStartGrowing', 'GrowingCopy'].includes(file.status)) {
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
            const files = Array.from(this.items.values());
            return this.sortFiles(files);
        },

        get activeFiles() {
            const files = Array.from(this.items.values())
                .filter(file => !['Completed', 'Failed'].includes(file.status));
            return this.sortFiles(files);
        },

        get completedFiles() {
            const files = Array.from(this.items.values())
                .filter(file => file.status === 'Completed');
            return this.sortFiles(files);
        },

        get growingFiles() {
            const files = Array.from(this.items.values())
                .filter(file => file.is_growing_file || ['Growing', 'ReadyToStartGrowing', 'GrowingCopy'].includes(file.status));
            return this.sortFiles(files);
        },

        get failedFiles() {
            const files = Array.from(this.items.values())
                .filter(file => file.status === 'Failed');
            return this.sortFiles(files);
        },

        // Sorting Logic
        sortFiles(files) {
            return files.sort((a, b) => {
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
                        const aName = a.file_path.split(/[/\\]/).pop().toLowerCase();
                        const bName = b.file_path.split(/[/\\]/).pop().toLowerCase();
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