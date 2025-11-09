// @ts-check

/**
 * @file Directory Browser Store - Alpine.js store for file/folder browsing modal
 *
 * Handles directory scanning, file listing, and modal state management.
 * Integrates with DirectoryScannerService backend endpoints.
 */



document.addEventListener('alpine:init', () => {
    Alpine.store('directoryBrowser', {
        // === STATE ===

        /** @type {boolean} */
        isOpen: false,
        /** @type {string} */
        currentPath: '',
        /** @type {ScanType|''} */
        scanType: '',
        /** @type {string} */
        modalTitle: '',

        /** @type {boolean} */
        isLoading: false,
        /** @type {boolean} */
        isAccessible: false,
        /** @type {DirectoryItem[]} */
        items: [],
        /** @type {DirectoryItem[]} */
        treeStructure: [],
        /** @type {number} */
        totalItems: 0,
        /** @type {number} */
        totalFiles: 0,
        /** @type {number} */
        totalDirectories: 0,
        /** @type {number} */
        scanDuration: 0,
        /** @type {string|null} */
        errorMessage: null,

        /** @type {SortField} */
        sortBy: 'name',
        /** @type {SortDirection} */
        sortDirection: 'asc',
        /** @type {boolean} */
        showHidden: false,
        /** @type {boolean} */
        recursive: true,
        /** @type {number} */
        maxDepth: 3,
        /** @type {ViewMode} */
        viewMode: 'tree',

        /** @type {Set<string>} */
        expandedDirectories: new Set(),
        /** @type {boolean} */
        defaultExpanded: true,

        // === METHODS ===

        /**
         * Opens the modal for source directory browsing.
         */
        openSourceBrowser() {
            this.scanType = 'source';
            this.modalTitle = '📁 Source Directory Browser';
            this.isOpen = true;
            this.scanDirectory();
        },

        /**
         * Opens the modal for destination directory browsing.
         */
        openDestinationBrowser() {
            this.scanType = 'destination';
            this.modalTitle = '🎯 Destination Directory Browser';
            this.isOpen = true;
            this.scanDirectory();
        },

        /**
         * Closes the modal and resets the store's state.
         */
        closeModal() {
            this.isOpen = false;
            this.resetState();
        },

        /**
         * Resets the internal state of the store to its default values.
         */
        resetState() {
            this.currentPath = '';
            this.scanType = '';
            this.modalTitle = '';
            this.isLoading = false;
            this.isAccessible = false;
            this.items = [];
            this.treeStructure = [];
            this.totalItems = 0;
            this.totalFiles = 0;
            this.totalDirectories = 0;
            this.scanDuration = 0;
            this.errorMessage = null;
        },

        /**
         * Scans the current directory by calling the backend API.
         * @returns {Promise<void>}
         */
        async scanDirectory() {
            if (!this.scanType) {
                console.error('DirectoryBrowser: No scan type specified');
                return;
            }

            this.isLoading = true;
            this.errorMessage = null;

            try {
                const endpoint = this.scanType === 'source'
                    ? '/api/directory/scan/source'
                    : '/api/directory/scan/destination';

                const params = new URLSearchParams({
                    recursive: this.recursive.toString(),
                    max_depth: this.maxDepth.toString()
                });

                const url = `${endpoint}?${params}`;
                console.log(`DirectoryBrowser: Scanning ${this.scanType} directory (recursive=${this.recursive}, depth=${this.maxDepth})...`);

                const response = await fetch(url);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                /** @type {DirectoryScanResult} */
                const data = await response.json();

                this.currentPath = data.path;
                this.isAccessible = data.is_accessible;
                this.items = data.items || [];
                this.treeStructure = data.tree || [];
                this.totalItems = data.total_items || 0;
                this.totalFiles = data.total_files || 0;
                this.totalDirectories = data.total_directories || 0;
                this.scanDuration = data.scan_duration_seconds || 0;
                this.errorMessage = data.error_message;

                if (this.defaultExpanded && this.viewMode === 'tree') {
                    this.expandAllDirectories();
                }
                console.log(`DirectoryBrowser: Scan completed - ${this.totalItems} items found (${this.totalFiles} files, ${this.totalDirectories} dirs)`);

            } catch (error) {
                console.error('DirectoryBrowser: Scan failed:', error);
                if (error instanceof Error) {
                    this.errorMessage = `Failed to scan directory: ${error.message}`;
                } else {
                    this.errorMessage = 'Failed to scan directory: An unknown error occurred.';
                }
                this.isAccessible = false;
                this.items = [];
            } finally {
                this.isLoading = false;
            }
        },

        /**
         * Gets the items to be displayed, processed for the current view mode (tree or flat).
         * @returns {DirectoryItem[]} A flattened list of items ready for rendering.
         */
        get displayItems() {
            if (this.viewMode === 'tree') {
                return this._getFlattenedTreeItems(this.treeStructure);
            } else {
                let filtered = this.items;
                if (!this.showHidden) {
                    filtered = filtered.filter((/** @type {DirectoryItem} */ item) => !item.is_hidden);
                }
                return this._getFlatViewItems(filtered);
            }
        },

        /**
         * Recursively flattens the nested tree structure for rendering, respecting expanded/collapsed states.
         * @param {DirectoryItem[]} treeItems - The nested items to flatten.
         * @param {number} [depth=0] - The current recursion depth.
         * @returns {DirectoryItem[]} The flattened list.
         * @private
         */
        _getFlattenedTreeItems(treeItems, depth = 0) {
            /** @type {DirectoryItem[]} */
            const flatItems = [];
            if (!treeItems || !Array.isArray(treeItems)) {
                return flatItems;
            }

            for (const item of treeItems) {
                if (!this.showHidden && item.is_hidden) {
                    continue;
                }

                const flatItem = { ...item, depth_level: depth };
                flatItems.push(flatItem);

                if (item.is_directory && item.children && item.children.length > 0 && this.isDirectoryExpanded(item.path)) {
                    const childItems = this._getFlattenedTreeItems(item.children, depth + 1);
                    flatItems.push(...childItems);
                }
            }
            return flatItems;
        },

        /**
         * Sorts a flat list of items based on the current sort settings.
         * @param {DirectoryItem[]} items - The items to sort.
         * @returns {DirectoryItem[]} The sorted list.
         * @private
         */
        _getFlatViewItems(items) {
            return [...items].sort((/** @type {DirectoryItem} */ a, /** @type {DirectoryItem} */ b) => {
                let comparison = 0;
                switch (this.sortBy) {
                    case 'name':
                        if (a.is_directory !== b.is_directory) return a.is_directory ? -1 : 1;
                        comparison = a.name.localeCompare(b.name);
                        break;
                    case 'size':
                        if (a.is_directory && !b.is_directory) return -1;
                        if (!a.is_directory && b.is_directory) return 1;
                        comparison = (a.size_bytes || 0) - (b.size_bytes || 0);
                        break;
                    case 'created':
                        comparison = new Date(a.created_time || 0).getTime() - new Date(b.created_time || 0).getTime();
                        break;
                    case 'modified':
                        comparison = new Date(a.modified_time || 0).getTime() - new Date(b.modified_time || 0).getTime();
                        break;
                    case 'type':
                        if (a.is_directory && !b.is_directory) return -1;
                        if (!a.is_directory && b.is_directory) return 1;
                        const extA = a.name.split('.').pop() || '';
                        const extB = b.name.split('.').pop() || '';
                        comparison = extA.localeCompare(extB);
                        break;
                }
                return this.sortDirection === 'asc' ? comparison : -comparison;
            });
        },

        /**
         * Gets the indentation style for a tree view item.
         * @param {DirectoryItem} item - The directory item.
         * @returns {{paddingLeft: string}} A style object.
         */
        getTreeIndentation(item) {
            const paddingLeft = item.depth_level * 20;
            return { paddingLeft: `${paddingLeft}px` };
        },

        /**
         * Gets the expand/collapse icon for a directory in tree view.
         * @param {DirectoryItem} item - The directory item.
         * @returns {string|null} An emoji icon or null.
         */
        getTreeIcon(item) {
            if (!item.is_directory) return null;
            return this.isDirectoryExpanded(item.path) ? '📂' : '📁';
        },

        /**
         * Sets the sort field and direction.
         * @param {SortField} field - The field to sort by.
         */
        setSortBy(field) {
            if (this.sortBy === field) {
                this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                this.sortBy = field;
                this.sortDirection = 'asc';
            }
            this.viewMode = 'flat';
        },

        /**
         * Toggles the visibility of hidden files.
         */
        toggleHidden() {
            this.showHidden = !this.showHidden;
        },

        /**
         * Toggles recursive scanning on or off.
         */
        toggleRecursive() {
            this.recursive = !this.recursive;
        },

        /**
         * Sets the maximum recursion depth for scanning.
         * @param {string|number} depth - The desired depth.
         */
        setMaxDepth(depth) {
            const newDepth = parseInt(String(depth), 10);
            if (newDepth >= 1 && newDepth <= 10) {
                this.maxDepth = newDepth;
            }
        },

        /**
         * Toggles the view mode between 'tree' and 'flat'.
         */
        toggleViewMode() {
            this.viewMode = this.viewMode === 'tree' ? 'flat' : 'tree';
            if (this.viewMode === 'tree' && this.defaultExpanded) {
                this.expandAllDirectories();
            }
        },

        /**
         * Toggles the expanded/collapsed state of a directory.
         * @param {string} directoryPath - The path of the directory to toggle.
         */
        toggleDirectory(directoryPath) {
            if (this.expandedDirectories.has(directoryPath)) {
                this.expandedDirectories.delete(directoryPath);
            } else {
                this.expandedDirectories.add(directoryPath);
            }
            this.expandedDirectories = new Set(this.expandedDirectories);
        },

        /**
         * Checks if a directory is currently expanded.
         * @param {string} directoryPath - The path of the directory to check.
         * @returns {boolean}
         */
        isDirectoryExpanded(directoryPath) {
            return this.expandedDirectories.has(directoryPath);
        },

        /**
         * Expands all directories in the current view.
         */
        expandAllDirectories() {
            const directories = this.items.filter((/** @type {DirectoryItem} */ item) => item.is_directory);
            directories.forEach((/** @type {DirectoryItem} */ dir) => this.expandedDirectories.add(dir.path));
            this.expandedDirectories = new Set(this.expandedDirectories);
        },

        /**
         * Collapses all directories.
         */
        collapseAllDirectories() {
            this.expandedDirectories.clear();
            this.expandedDirectories = new Set();
        },

        /**
         * Formats a file size in bytes into a human-readable string.
         * @param {number|null|undefined} bytes - The size in bytes.
         * @returns {string} The formatted size string.
         */
        formatFileSize(bytes) {
            if (!bytes || bytes === 0) return '';
            const units = ['B', 'KB', 'MB', 'GB', 'TB'];
            let size = bytes;
            let unitIndex = 0;
            while (size >= 1024 && unitIndex < units.length - 1) {
                size /= 1024;
                unitIndex++;
            }
            return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
        },

        /**
         * Formats an ISO date string into a localized string.
         * @param {string|null|undefined} dateString - The ISO date string.
         * @returns {string} The formatted date string.
         */
        formatDateTime(dateString) {
            if (!dateString) return '';
            try {
                const date = new Date(dateString);
                return date.toLocaleString('da-DK', {
                    year: 'numeric', month: '2-digit', day: '2-digit',
                    hour: '2-digit', minute: '2-digit', second: '2-digit'
                });
            } catch (error) {
                return dateString;
            }
        },

        /**
         * Gets a file icon based on the item type and extension.
         * @param {DirectoryItem} item - The directory item.
         * @returns {string} An emoji icon.
         */
        getFileIcon(item) {
            if (item.is_directory) {
                return item.is_hidden ? '📁' : '📂';
            }
            const extension = item.name.split('.').pop()?.toLowerCase() || '';
            switch (extension) {
                case 'mxf': case 'mov': case 'mp4': case 'avi': return '🎬';
                case 'jpg': case 'jpeg': case 'png': case 'gif': return '🖼️';
                case 'txt': case 'log': return '📄';
                case 'pdf': return '📕';
                case 'zip': case 'rar': case '7z': return '📦';
                default: return item.is_hidden ? '📄' : '📄';
            }
        },

        /**
         * Gets a summary object for the current status.
         * @returns {{text: string, color: string, icon: string}}
         */
        get statusSummary() {
            if (!this.isAccessible && this.errorMessage) {
                return { text: 'Error', color: 'text-red-400', icon: '❌' };
            }
            if (!this.isAccessible) {
                return { text: 'Utilgængelig', color: 'text-red-400', icon: '🚫' };
            }
            if (this.isLoading) {
                return { text: 'Indlæser...', color: 'text-blue-400', icon: '⏳' };
            }
            return {
                text: `${this.totalItems} elementer (${this.totalFiles} filer, ${this.totalDirectories} mapper)`,
                color: 'text-green-400',
                icon: '✅'
            };
        }
    });
});