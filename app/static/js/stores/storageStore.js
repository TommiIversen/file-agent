/**
 * Storage Store - Storage Information Management
 * 
 * Centralized state for source and destination storage monitoring,
 * status tracking, and health calculation with Alpine.js store pattern.
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('storage', {
        // Storage State
        source: null,
        destination: null,
        overall_status: 'Unknown',
        
        // Mount Status State
        mountStatus: {
            source: null,
            destination: null
        },
        
        // Loading State
        isLoading: false,
        lastUpdated: null,
        
        // Storage Management Actions
        updateSource(data) {
            this.source = data;
            this.updateOverallStatus();
            this.lastUpdated = new Date();
            console.log('Source storage updated:', data);
        },
        
        updateDestination(data) {
            this.destination = data;
            this.updateOverallStatus();
            this.lastUpdated = new Date();
            console.log('Destination storage updated:', data);
        },
        
        updateOverallStatus() {
            const sourceStatus = this.source?.status;
            const destStatus = this.destination?.status;
            
            // Priority: CRITICAL > ERROR > WARNING > OK
            const priorities = {
                'CRITICAL': 4,
                'ERROR': 3,
                'WARNING': 2,
                'OK': 1
            };
            
            const sourcePriority = priorities[sourceStatus] || 0;
            const destPriority = priorities[destStatus] || 0;
            
            if (sourcePriority >= destPriority) {
                this.overall_status = sourceStatus || 'Unknown';
            } else {
                this.overall_status = destStatus || 'Unknown';
            }
            
            console.log(`Overall storage status: ${this.overall_status}`);
        },

        // Storage Update Handlers (for WebSocket messages)
        handleStorageUpdate(data) {
            console.log('Storage update received:', data);
            
            if (data.storage_type === 'source') {
                this.updateSource(data.storage_info);
            } else if (data.storage_type === 'destination') {
                this.updateDestination(data.storage_info);
            }
        },
        
        // Mount Status Update Handler
        handleMountStatus(data) {
            console.log('Mount status update received:', data);
            
            this.mountStatus[data.storage_type] = {
                status: data.mount_status,
                shareUrl: data.share_url,
                mountPath: data.mount_path,
                targetPath: data.target_path,
                errorMessage: data.error_message,
                timestamp: new Date(data.timestamp)
            };
            
            this.lastUpdated = new Date();
        },
        
        // Computed Properties - Source
        get sourceStatus() {
            return this.source?.status || 'Unknown';
        },
        
        get sourceStatusColor() {
            switch (this.sourceStatus) {
                case 'OK': return 'bg-green-500';
                case 'WARNING': return 'bg-yellow-500';
                case 'ERROR':
                case 'CRITICAL': return 'bg-red-500';
                default: return 'bg-gray-500';
            }
        },
        
        get sourceStatusTextColor() {
            switch (this.sourceStatus) {
                case 'OK': return 'text-green-400';
                case 'WARNING': return 'text-yellow-400';
                case 'ERROR':
                case 'CRITICAL': return 'text-red-400';
                default: return 'text-gray-400';
            }
        },
        
        get sourceUsagePercentage() {
            if (!this.source || !this.source.total_space_gb) return 0;
            return ((this.source.total_space_gb - this.source.free_space_gb) / this.source.total_space_gb) * 100;
        },
        
        get sourceFreeSpaceFormatted() {
            return UIHelpers.formatSizeFromGB(this.source?.free_space_gb);
        },
        
        get sourceTotalSpaceFormatted() {
            return UIHelpers.formatSizeFromGB(this.source?.total_space_gb);
        },
        
        // Computed Properties - Destination
        get destinationStatus() {
            return this.destination?.status || 'Unknown';
        },
        
        get destinationStatusColor() {
            switch (this.destinationStatus) {
                case 'OK': return 'bg-green-500';
                case 'WARNING': return 'bg-yellow-500';
                case 'ERROR':
                case 'CRITICAL': return 'bg-red-500';
                default: return 'bg-gray-500';
            }
        },
        
        get destinationStatusTextColor() {
            switch (this.destinationStatus) {
                case 'OK': return 'text-green-400';
                case 'WARNING': return 'text-yellow-400';
                case 'ERROR':
                case 'CRITICAL': return 'text-red-400';
                default: return 'text-gray-400';
            }
        },
        
        get destinationUsagePercentage() {
            if (!this.destination || !this.destination.total_space_gb) return 0;
            return ((this.destination.total_space_gb - this.destination.free_space_gb) / this.destination.total_space_gb) * 100;
        },
        
        get destinationFreeSpaceFormatted() {
            return UIHelpers.formatSizeFromGB(this.destination?.free_space_gb);
        },
        
        get destinationTotalSpaceFormatted() {
            return UIHelpers.formatSizeFromGB(this.destination?.total_space_gb);
        },

        // Access Status Helpers
        get sourceAccessible() {
            return this.source?.is_accessible || false;
        },
        
        get sourceWritable() {
            return this.source?.has_write_access || false;
        },
        
        get destinationAccessible() {
            return this.destination?.is_accessible || false;
        },
        
        get destinationWritable() {
            return this.destination?.has_write_access || false;
        },
        
        // Mount Status Computed Properties
        get sourceMountStatus() {
            return this.mountStatus.source?.status || null;
        },
        
        get destinationMountStatus() {
            return this.mountStatus.destination?.status || null;
        },
        
        get sourceMountStatusColor() {
            switch (this.sourceMountStatus) {
                case 'SUCCESS': return 'text-green-400';
                case 'ATTEMPTING': return 'text-blue-400';
                case 'FAILED': return 'text-red-400';
                case 'NOT_CONFIGURED': return 'text-gray-400';
                default: return 'text-gray-500';
            }
        },
        
        get destinationMountStatusColor() {
            switch (this.destinationMountStatus) {
                case 'SUCCESS': return 'text-green-400';
                case 'ATTEMPTING': return 'text-blue-400';
                case 'FAILED': return 'text-red-400';
                case 'NOT_CONFIGURED': return 'text-gray-400';
                default: return 'text-gray-500';
            }
        },
        
        get destinationMountMessage() {
            const mount = this.mountStatus.destination;
            if (!mount) return null;
            
            switch (mount.status) {
                case 'ATTEMPTING':
                    return `Mounting ${mount.shareUrl}...`;
                case 'SUCCESS':
                    return `Mounted ${mount.shareUrl}`;
                case 'FAILED':
                    return `Mount failed: ${mount.errorMessage || 'Unknown error'}`;
                case 'NOT_CONFIGURED':
                    return 'Network mount not configured';
                default:
                    return null;
            }
        }
    });
});