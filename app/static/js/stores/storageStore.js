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
        
        // Data Loading
        async loadStorageData() {
            if (this.isLoading) return;
            
            this.isLoading = true;
            console.log('Loading storage data...');
            
            try {
                const response = await fetch('/api/storage');
                if (response.ok) {
                    const data = await response.json();
                    this.source = data.source;
                    this.destination = data.destination;
                    this.overall_status = data.overall_status;
                    this.lastUpdated = new Date();
                    console.log('Storage data loaded successfully:', data);
                } else {
                    console.error('Failed to load storage data:', response.statusText);
                }
            } catch (error) {
                console.error('Error loading storage data:', error);
            } finally {
                this.isLoading = false;
            }
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
        
        get sourceFreeSpaceGB() {
            return this.source?.free_space_gb?.toFixed(1) || '0.0';
        },
        
        get sourceTotalSpaceGB() {
            return this.source?.total_space_gb?.toFixed(1) || '0.0';
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
        
        get destinationFreeSpaceGB() {
            return this.destination?.free_space_gb?.toFixed(1) || '0.0';
        },
        
        get destinationTotalSpaceGB() {
            return this.destination?.total_space_gb?.toFixed(1) || '0.0';
        },
        
        // Computed Properties - Overall
        get overallStatusColor() {
            switch (this.overall_status) {
                case 'OK': return 'bg-green-500';
                case 'WARNING': return 'bg-yellow-500';
                case 'ERROR':
                case 'CRITICAL': return 'bg-red-500';
                default: return 'bg-gray-500';
            }
        },
        
        get hasStorageData() {
            return this.source && this.destination;
        },
        
        get isHealthy() {
            return this.overall_status === 'OK';
        },
        
        get needsAttention() {
            return ['WARNING', 'ERROR', 'CRITICAL'].includes(this.overall_status);
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
        }
    });
});