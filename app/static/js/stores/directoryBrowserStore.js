/**
 * Directory Browser Store - Alpine.js store for file/folder browsing modal
 * 
 * Handles directory scanning, file listing, and modal state management.
 * Integrates with DirectoryScannerService backend endpoints.
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('directoryBrowser', {
        // Modal state
        isOpen: false,
        currentPath: '',
        scanType: '', // 'source' or 'destination'
        modalTitle: '',
        
        // Directory scan data
        isLoading: false,
        isAccessible: false,
        items: [],
        totalItems: 0,
        totalFiles: 0,
        totalDirectories: 0,
        scanDuration: 0,
        errorMessage: null,
        
        // UI state
        sortBy: 'name', // 'name', 'size', 'created', 'modified', 'type'
        sortDirection: 'asc', // 'asc' or 'desc'
        showHidden: false,
        
        /**
         * Open modal for source directory browsing
         */
        openSourceBrowser() {
            this.scanType = 'source';
            this.modalTitle = '📁 Source Directory Browser';
            this.isOpen = true;
            this.scanDirectory();
        },
        
        /**
         * Open modal for destination directory browsing
         */
        openDestinationBrowser() {
            this.scanType = 'destination';
            this.modalTitle = '🎯 Destination Directory Browser';
            this.isOpen = true;
            this.scanDirectory();
        },
        
        /**
         * Close the modal and reset state
         */
        closeModal() {
            this.isOpen = false;
            this.resetState();
        },
        
        /**
         * Reset internal state
         */
        resetState() {
            this.currentPath = '';
            this.scanType = '';
            this.modalTitle = '';
            this.isLoading = false;
            this.isAccessible = false;
            this.items = [];
            this.totalItems = 0;
            this.totalFiles = 0;
            this.totalDirectories = 0;
            this.scanDuration = 0;
            this.errorMessage = null;
        },
        
        /**
         * Scan current directory using backend API
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
                    
                console.log(`DirectoryBrowser: Scanning ${this.scanType} directory...`);
                
                const response = await fetch(endpoint);
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                const data = await response.json();
                
                // Update state with scan results
                this.currentPath = data.path;
                this.isAccessible = data.is_accessible;
                this.items = data.items || [];
                this.totalItems = data.total_items || 0;
                this.totalFiles = data.total_files || 0;
                this.totalDirectories = data.total_directories || 0;
                this.scanDuration = data.scan_duration_seconds || 0;
                this.errorMessage = data.error_message;
                
                console.log(`DirectoryBrowser: Scan completed - ${this.totalItems} items found`);
                
            } catch (error) {
                console.error('DirectoryBrowser: Scan failed:', error);
                this.errorMessage = `Failed to scan directory: ${error.message}`;
                this.isAccessible = false;
                this.items = [];
            } finally {
                this.isLoading = false;
            }
        },
        
        /**
         * Get filtered and sorted items for display
         */
        get displayItems() {
            let filtered = this.items;
            
            // Filter hidden files if not showing them
            if (!this.showHidden) {
                filtered = filtered.filter(item => !item.is_hidden);
            }
            
            // Sort items
            filtered.sort((a, b) => {
                let comparison = 0;
                
                switch (this.sortBy) {
                    case 'name':
                        comparison = a.name.localeCompare(b.name);
                        break;
                    case 'size':
                        // Directories first, then by size
                        if (a.is_directory && !b.is_directory) return -1;
                        if (!a.is_directory && b.is_directory) return 1;
                        comparison = (a.size_bytes || 0) - (b.size_bytes || 0);
                        break;
                    case 'created':
                        comparison = new Date(a.created_time || 0) - new Date(b.created_time || 0);
                        break;
                    case 'modified':
                        comparison = new Date(a.modified_time || 0) - new Date(b.modified_time || 0);
                        break;
                    case 'type':
                        // Directories first, then by file extension
                        if (a.is_directory && !b.is_directory) return -1;
                        if (!a.is_directory && b.is_directory) return 1;
                        const extA = a.name.split('.').pop() || '';
                        const extB = b.name.split('.').pop() || '';
                        comparison = extA.localeCompare(extB);
                        break;
                }
                
                return this.sortDirection === 'asc' ? comparison : -comparison;
            });
            
            return filtered;
        },
        
        /**
         * Toggle sort direction or change sort field
         */
        setSortBy(field) {
            if (this.sortBy === field) {
                // Toggle direction if same field
                this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                // Change field and reset to ascending
                this.sortBy = field;
                this.sortDirection = 'asc';
            }
        },
        
        /**
         * Toggle hidden files visibility
         */
        toggleHidden() {
            this.showHidden = !this.showHidden;
        },
        
        /**
         * Format file size for display
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
         * Format datetime for display
         */
        formatDateTime(dateString) {
            if (!dateString) return '';
            
            try {
                const date = new Date(dateString);
                return date.toLocaleString('da-DK', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                });
            } catch (error) {
                return dateString;
            }
        },
        
        /**
         * Get file icon based on type
         */
        getFileIcon(item) {
            if (item.is_directory) {
                return item.is_hidden ? '📁' : '📂';
            }
            
            const extension = item.name.split('.').pop()?.toLowerCase() || '';
            
            switch (extension) {
                case 'mxf':
                case 'mov':
                case 'mp4':
                case 'avi':
                    return '🎬';
                case 'jpg':
                case 'jpeg':
                case 'png':
                case 'gif':
                    return '🖼️';
                case 'txt':
                case 'log':
                    return '📄';
                case 'pdf':
                    return '📕';
                case 'zip':
                case 'rar':
                case '7z':
                    return '📦';
                default:
                    return item.is_hidden ? '📄' : '📄';
            }
        },
        
        /**
         * Get status summary for display
         */
        get statusSummary() {
            if (!this.isAccessible && this.errorMessage) {
                return {
                    text: 'Error',
                    color: 'text-red-400',
                    icon: '❌'
                };
            }
            
            if (!this.isAccessible) {
                return {
                    text: 'Utilgængelig',
                    color: 'text-red-400',
                    icon: '🚫'
                };
            }
            
            if (this.isLoading) {
                return {
                    text: 'Indlæser...',
                    color: 'text-blue-400',
                    icon: '⏳'
                };
            }
            
            return {
                text: `${this.totalItems} elementer (${this.totalFiles} filer, ${this.totalDirectories} mapper)`,
                color: 'text-green-400',
                icon: '✅'
            };
        }
    });
});