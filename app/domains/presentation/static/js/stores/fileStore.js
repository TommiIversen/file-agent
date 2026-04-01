// @ts-check

/**
 * @file File Store - File State Management
 *
 * Centralized state for file tracking, statistics, sorting,
 * and file lifecycle management with Alpine.js store pattern.
 */



document.addEventListener('alpine:init', () => {
    Alpine.store('files', {
        // === STATE ===

        /** @type {Map<string, TrackedFile>} - Map of fileId to TrackedFile object. */
        items: new Map(),
        /** @type {SortBy} - Current sort method. */
        sortBy: 'discovered',
        /** @type {ActiveFilter} - Current active filter. */
        activeFilter: 'all',

        /** @type {boolean} */
        isLoadingMore: false,
        /** @type {boolean} */
        hasMore: true,
        /** @type {number} - Tracks how many files have been loaded for offset pagination. */
        loadedCount: 0,
        PAGE_SIZE: 20,

        /** Statistics about the files. */
        statistics: {
            /** @type {number} */
            totalFiles: 0,
            /** @type {number} */
            activeFiles: 0,
            /** @type {number} */
            completedFiles: 0,
            /** @type {number} */
            failedFiles: 0,
            /** @type {number} */
            growingFiles: 0
        },

        // === METHODS ===

        /**
         * Sets the active file filter.
         * @param {ActiveFilter} filterName - The name of the filter to apply.
         */
        setFilter(filterName) {
            this.activeFilter = filterName;
            console.log(`Filter changed to: ${filterName}`);
        },

        /**
         * Adds a new file to the store.
         * @param {TrackedFile} file - The file object to add.
         */
        addFile(file) {
            if (!file || !file.id) {
                console.error('addFile called with invalid file object:', file);
                return;
            }

            this.items.set(file.id, file);
            this.updateStatisticsFromFiles();
            console.log(`File added: ${file.file_path} (ID: ${file.id})`);
        },

        /**
         * Updates an existing file with partial data.
         * @param {string} fileId - The ID of the file to update.
         * @param {Partial<TrackedFile>} partialFile - An object with properties to update.
         */
        updateFile(fileId, partialFile) {
            if (!fileId || !partialFile) {
                console.error('updateFile called with invalid parameters:', { fileId, partialFile });
                return;
            }

            if (this.items.has(fileId)) {
                const existingFile = this.items.get(fileId);
                if (existingFile) {
                    Object.assign(existingFile, partialFile);
                    if (partialFile.status) {
                        console.log(`File updated: ${existingFile.file_path} (ID: ${fileId}) - Status: ${partialFile.status}`);
                        this.updateStatisticsFromFiles();
                    }
                }
            } else {
                if (partialFile.id && partialFile.file_path) {
                    const discoveredFile = Array.from(this.items.entries()).find(([, file]) =>
                        file.file_path === partialFile.file_path && file.isDiscovered
                    );

                    if (discoveredFile) {
                        this.items.delete(discoveredFile[0]);
                    }
                    this.addFile(/** @type {TrackedFile} */ (partialFile));
                } else {
                    console.warn(`Ignoring partial update for unknown file: ${fileId}`);
                }
            }
        },

        /**
         * Adds a newly discovered file, giving it a temporary ID.
         * @param {Partial<TrackedFile>} discoveredFile - The discovered file data.
         */
        addDiscoveredFile(discoveredFile) {
            if (!discoveredFile || !discoveredFile.file_path) {
                console.error('addDiscoveredFile called with invalid parameters:', discoveredFile);
                return;
            }

            const existingFile = Array.from(this.items.values()).find((/** @type {TrackedFile} */ file) =>
                file.file_path === discoveredFile.file_path
            );

            if (existingFile) {
                if (!existingFile.id) {
                    Object.assign(existingFile, discoveredFile);
                }
                return;
            }

            const tempId = `discovered_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            discoveredFile.id = tempId;
            discoveredFile.isDiscovered = true;

            this.items.set(tempId, /** @type {TrackedFile} */ (discoveredFile));
            this.updateStatisticsFromFiles();
            console.log(`Discovered file added: ${discoveredFile.file_path} (temp ID: ${tempId})`);
        },

        /**
         * Sets the initial list of files, clearing any existing ones.
         * @param {TrackedFile[]} files - An array of file objects.
         */
        setInitialFiles(files) {
            if (!Array.isArray(files)) {
                console.error('setInitialFiles called with non-array:', files);
                return;
            }

            console.log('Setting initial files:', files.length);
            this.items.clear();

            files.forEach((/** @type {TrackedFile} */ file) => {
                if (file && file.id) {
                    this.items.set(file.id, file);
                } else {
                    console.warn('Skipping invalid file in setInitialFiles:', file);
                }
            });

            this.loadedCount = files.length;
            this.hasMore = files.length >= this.PAGE_SIZE;
            this.updateStatisticsFromFiles();
        },

        /**
         * Loads the next page of files from the API (infinite scroll).
         */
        async loadMore() {
            if (this.isLoadingMore || !this.hasMore) return;
            this.isLoadingMore = true;
            try {
                const params = new URLSearchParams();
                params.append('limit', String(this.PAGE_SIZE));
                params.append('offset', String(this.loadedCount));
                const response = await fetch(`/api/files?${params.toString()}`);
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const files = await response.json();
                if (files.length === 0) {
                    this.hasMore = false;
                } else {
                    files.forEach((/** @type {TrackedFile} */ file) => {
                        if (file && file.id && !this.items.has(file.id)) {
                            this.items.set(file.id, file);
                        }
                    });
                    this.loadedCount += files.length;
                    this.hasMore = files.length >= this.PAGE_SIZE;
                    this.updateStatisticsFromFiles();
                }
            } catch (err) {
                console.error('Failed to load more files:', err);
            } finally {
                this.isLoadingMore = false;
            }
        },

        /**
         * Handles scroll events for infinite scroll.
         * @param {Event} event
         */
        handleFilesScroll(event) {
            const el = event.target;
            const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 200;
            if (nearBottom && !this.isLoadingMore && this.hasMore) {
                this.loadMore();
            }
        },

        /**
         * Sets the sorting method for the file list.
         * @param {SortBy} sortMethod - The sort method to use.
         */
        setSortBy(sortMethod) {
            this.sortBy = sortMethod;
            console.log(`Sort method changed to: ${sortMethod}`);
        },

        /**
         * Updates the statistics object from an external source.
         * @param {Partial<typeof this.statistics>} stats - The statistics object.
         */
        updateStatistics(stats) {
            if (stats) {
                this.statistics.totalFiles = stats.totalFiles || 0;
                this.statistics.activeFiles = stats.activeFiles || 0;
                this.statistics.completedFiles = stats.completedFiles || 0;
                this.statistics.failedFiles = stats.failedFiles || 0;
                this.statistics.growingFiles = stats.growingFiles || 0;
            }
        },

        /**
         * Recalculates statistics based on the current files in the store.
         */
        updateStatisticsFromFiles() {
            const stats = { total: this.items.size, active: 0, completed: 0, failed: 0, growing: 0 };

            this.items.forEach((/** @type {TrackedFile} */ file) => {
                if (['Growing', 'ReadyToStartGrowing', 'GrowingCopy'].includes(file.status)) {
                    stats.growing++;
                }
                switch (file.status) {
                    case 'Completed': stats.completed++; break;
                    case 'Failed': stats.failed++; break;
                    default: stats.active++;
                }
            });

            this.statistics.totalFiles = stats.total;
            this.statistics.activeFiles = stats.active;
            this.statistics.completedFiles = stats.completed;
            this.statistics.failedFiles = stats.failed;
            this.statistics.growingFiles = stats.growing;
        },

        /**
         * Gets a filtered and sorted list of files based on the current UI state.
         * @returns {TrackedFile[]}
         */
        get filteredFiles() {
            let filesToFilter = Array.from(this.items.values());

            switch (this.activeFilter) {
                case 'active':
                    filesToFilter = filesToFilter.filter((/** @type {TrackedFile} */ file) => !['Completed', 'Failed'].includes(file.status));
                    break;
                case 'completed':
                    filesToFilter = filesToFilter.filter((/** @type {TrackedFile} */ file) => file.status === 'Completed');
                    break;
                case 'growing':
                    filesToFilter = filesToFilter.filter((/** @type {TrackedFile} */ file) => ['Growing', 'ReadyToStartGrowing', 'GrowingCopy'].includes(file.status));
                    break;
                case 'failed':
                    filesToFilter = filesToFilter.filter((/** @type {TrackedFile} */ file) => file.status === 'Failed');
                    break;
                case 'all':
                default:
                    break;
            }
            return this.sortFiles(filesToFilter);
        },

        /**
         * Gets all files, sorted.
         * @returns {TrackedFile[]}
         */
        get allFiles() {
            if (!this.items) return [];
            const files = Array.from(this.items.values());
            return this.sortFiles(files);
        },

        /**
         * Gets all active (non-completed, non-failed) files, sorted.
         * @returns {TrackedFile[]}
         */
        get activeFiles() {
            if (!this.items) return [];
            const files = Array.from(this.items.values()).filter((/** @type {TrackedFile} */ file) => !['Completed', 'Failed'].includes(file.status));
            return this.sortFiles(files);
        },

        /**
         * Gets all completed files, sorted.
         * @returns {TrackedFile[]}
         */
        get completedFiles() {
            if (!this.items) return [];
            const files = Array.from(this.items.values()).filter((/** @type {TrackedFile} */ file) => file.status === 'Completed');
            return this.sortFiles(files);
        },

        /**
         * Gets all growing files, sorted.
         * @returns {TrackedFile[]}
         */
        get growingFiles() {
            if (!this.items) return [];
            const files = Array.from(this.items.values()).filter((/** @type {TrackedFile} */ file) => ['Growing', 'ReadyToStartGrowing', 'GrowingCopy'].includes(file.status));
            return this.sortFiles(files);
        },

        /**
         * Gets all failed files, sorted.
         * @returns {TrackedFile[]}
         */
        get failedFiles() {
            if (!this.items) return [];
            const files = Array.from(this.items.values()).filter((/** @type {TrackedFile} */ file) => file.status === 'Failed');
            return this.sortFiles(files);
        },

        /**
         * Sorts an array of files based on the current sort settings.
         * @param {TrackedFile[]} files - The array of files to sort.
         * @returns {TrackedFile[]} The sorted array.
         */
        sortFiles(files) {
            if (!files || !Array.isArray(files)) {
                console.warn('sortFiles called with invalid files array:', files);
                return [];
            }

            return files.sort((/** @type {TrackedFile} */ a, /** @type {TrackedFile} */ b) => {
                if (!a || !b) return 0;

                switch (this.sortBy) {
                    case 'activity':
                        const getRelevantTime = (/** @type {TrackedFile} */ file) => {
                            if (file.completed_at) return new Date(file.completed_at).getTime();
                            if (file.started_copying_at) return new Date(file.started_copying_at).getTime();
                            return new Date(file.discovered_at || 0).getTime();
                        };
                        return getRelevantTime(b) - getRelevantTime(a);

                    case 'discovered':
                        return new Date(b.discovered_at || 0).getTime() - new Date(a.discovered_at || 0).getTime();

                    case 'started':
                        const aStarted = a.started_copying_at ? new Date(a.started_copying_at).getTime() : 0;
                        const bStarted = b.started_copying_at ? new Date(b.started_copying_at).getTime() : 0;
                        return bStarted - aStarted;

                    case 'completed':
                        const aCompleted = a.completed_at ? new Date(a.completed_at).getTime() : 0;
                        const bCompleted = b.completed_at ? new Date(b.completed_at).getTime() : 0;
                        return bCompleted - aCompleted;

                    case 'filename':
                        const aName = a.file_path.split(/[\/]/).pop()?.toLowerCase() || '';
                        const bName = b.file_path.split(/[\/]/).pop()?.toLowerCase() || '';
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
