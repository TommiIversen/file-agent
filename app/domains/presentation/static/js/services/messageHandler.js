/**
 * Message Handler Service - WebSocket Message Processing
 *
 * Centralized message routing and processing for WebSocket messages.
 * Routes messages to appropriate stores and handles different message types.
 */

class MessageHandler {
    constructor() {
        this.fileStore = null;
        this.storageStore = null;
        this.connectionStore = null;
        this.messageQueue = [];

        // Initialize after Alpine is ready
        document.addEventListener('alpine:init', () => {
            // Use $nextTick to ensure all stores are ready
            Alpine.nextTick(() => {
                this.fileStore = Alpine.store('files');
                this.storageStore = Alpine.store('storage');
                this.connectionStore = Alpine.store('connection');
                console.log('MessageHandler initialized with stores');
                
                // Process any queued messages
                this.processQueue();
            });
        });
    }

    /**
     * Process any messages that were queued while stores were initializing
     */
    processQueue() {
        if (this.messageQueue.length > 0) {
            console.log(`Processing ${this.messageQueue.length} queued messages`);
            const messages = [...this.messageQueue];
            this.messageQueue = [];
            messages.forEach(message => this.handleMessage(message));
        }
    }

    /**
     * Main message handler - routes messages by type
     */
    handleMessage(message) {
        if (!message || !message.type) {
            console.warn('Invalid message received:', message);
            return;
        }

        // If stores aren't ready, queue the message for later
        if (!this.fileStore) {
            console.log('Stores not ready, queueing message:', message.type);
            this.messageQueue.push(message);
            return;
        }

        console.log('Processing WebSocket message:', message.type);

        try {
            switch (message.type) {
                case 'initial_state':
                    this.handleInitialState(message.data);
                    break;

                case 'file_update':
                    this.handleFileUpdate(message.data);
                    break;

                case 'file_discovered':
                    this.handleFileDiscovered(message.data);
                    break;

                case 'file_progress_update':
                    console.log('File progress update received:', message.data);
                    this.handleFileProgressUpdate(message.data);
                    break;

                case 'file_copy_completed':
                    console.log('File copy completed:', message.data);
                    this.handleFileCopyCompleted(message.data);
                    break;

                case 'statistics_update':
                    this.handleStatisticsUpdate(message.data);
                    break;

                case 'storage_update':
                    this.handleStorageUpdate(message.data);
                    break;

                case 'mount_status':
                    this.handleMountStatus(message.data);
                    break;

                case 'scanner_status':
                    this.handleScannerStatus(message.data);
                    break;

                case 'system_status':
                    this.handleSystemStatus(message.data);
                    break;

                default:
                    console.warn(`Unknown message type: ${message.type}`);
            }
        } catch (error) {
            console.error('Error processing message:', error, message);
        }
    }

    /**
     * Handle initial state when connection is established
     */
    handleInitialState(data) {
        console.log('Received initial state:', data);

        // Update files
        if (data.files && Array.isArray(data.files)) {
            this.fileStore.setInitialFiles(data.files);
        }

        // Update statistics
        if (data.statistics) {
            this.fileStore.updateStatistics(data.statistics);
        }

        // Update storage info if available
        if (data.storage) {
            if (data.storage.source) {
                this.storageStore?.updateSource(data.storage.source);
            }
            if (data.storage.destination) {
                this.storageStore?.updateDestination(data.storage.destination);
            }
            if (data.storage.overall_status) {
                this.storageStore.overall_status = data.storage.overall_status;
            }
            console.log('Storage data loaded from initial state');
        }

        // Update scanner status if available
        if (data.scanner) {
            const uiStore = Alpine.store('ui');
            if (uiStore) {
                uiStore.updateScannerStatus(data.scanner);
            }
            console.log('Scanner status loaded from initial state:', data.scanner);
        }

        console.log(`Initial state loaded: ${data.files?.length || 0} files`);
    }

    /**
     * Handle individual file updates
     */
    handleFileUpdate(data) {
        console.log('File update received:', data.file_path);

        if (!data.file || !data.file.id) {
            console.warn('Invalid file update data - missing file ID:', data);
            return;
        }

        // Update or add file using ID instead of file_path
        this.fileStore.updateFile(data.file.id, data.file);

        // Log significant status changes
        if (data.file.status) {
            console.log(`File ${data.file_path} (ID: ${data.file.id}) status: ${data.file.status}`);
        }
    }

    /**
     * Handle newly discovered files
     */
    handleFileDiscovered(data) {
        console.log('File discovered:', data.file_path);

        if (!data.file_path) {
            console.warn('Invalid file discovered data - missing file_path:', data);
            return;
        }

        // Create a simplified file object for discovered files
        // Since we don't have the full TrackedFile object yet, we create a minimal representation
        const discoveredFile = {
            file_path: data.file_path,
            file_size: data.file_size,
            file_size_mb: data.file_size_mb,
            status: data.status || 'DISCOVERED',
            last_write_time: data.last_write_time,
            discovered_at: data.timestamp,
            // These will be filled in when the file gets proper ID and full tracking
            id: null, 
            progress: 0,
            bytes_copied: 0
        };

        // Add to file store as a discovered file
        this.fileStore.addDiscoveredFile(discoveredFile);

        console.log(`File discovered: ${data.file_path} (${data.file_size_mb} MB)`);
    }

    /**
     * Handle file progress updates
     */
    handleFileProgressUpdate(data) {
        if (!this.fileStore) {
            // Don't log an error, as this can happen frequently
            return;
        }
        this.fileStore.updateFile(data.file_id, {
            copy_progress: data.progress_percent,
            bytes_copied: data.bytes_copied,
            file_size: data.total_bytes,
            copy_speed_mbps: data.copy_speed_mbps,
        });

        // If this is the final progress update, log it
        if (data.is_final) {
            console.log(`Final progress update: ${data.file_id} reached 100%`);
        }
    }

    /**
     * Handle file copy completion notifications
     */
    handleFileCopyCompleted(data) {
        console.log('File copy completed:', data.file_path);
        
        if (!this.fileStore) {
            return;
        }

        // Ensure the file shows as 100% completed with actual copied bytes
        this.fileStore.updateFile(data.file_id, {
            copy_progress: 100.0,
            bytes_copied: data.bytes_copied,
            file_size: data.bytes_copied,  // Update to actual copied size
            copy_speed_mbps: 0.0,
            destination_path: data.destination_path
        });

        // Log detailed completion info
        const sizeMB = (data.bytes_copied / (1024*1024)).toFixed(2);
        let logMessage = `✅ Copy completed: ${data.file_path} (${sizeMB} MB)`;
        
        // Add extra info for growing files
        if (data.is_growing_file) {
            const sourceMB = (data.source_size / (1024*1024)).toFixed(2);
            const destMB = (data.dest_size / (1024*1024)).toFixed(2);
            logMessage += ` - Growing file: source ${sourceMB} MB → dest ${destMB} MB`;
        }
        
        console.log(logMessage);

        // Could add a visual notification here if needed for growing files
        if (data.is_growing_file) {
            console.log(`📈 Growing file copy completed with size difference: ${data.source_size - data.dest_size} bytes`);
        }
    }

    /**
     * Handle statistics updates
     */
    handleStatisticsUpdate(data) {
        console.log('Statistics update received');

        if (data.statistics) {
            this.fileStore.updateStatistics(data.statistics);
        }
    }

    /**
     * Handle storage updates
     */
    handleStorageUpdate(data) {
        console.log('Storage update received:', data.storage_type);

        this.storageStore.handleStorageUpdate(data);
    }

    /**
     * Handle mount status updates
     */
    handleMountStatus(data) {
        console.log('Mount status update received:', data.storage_type, data.mount_status);

        this.storageStore.handleMountStatus(data);
    }

    /**
     * Handle scanner status updates
     */
    handleScannerStatus(data) {
        console.log('Scanner status update received:', data);

        const uiStore = Alpine.store('ui');
        if (uiStore) {
            uiStore.updateScannerStatus({
                scanning: data.scanning,
                paused: data.paused
            });
        }
    }

    /**
     * Handle system status updates
     */
    handleSystemStatus(data) {
        console.log('System status update received:', data);

        // Handle system-wide status updates
        if (data.overall_health) {
            // Update overall system health
            console.log(`System health: ${data.overall_health}`);
        }

        if (data.services) {
            // Update service status
            console.log('Service status:', data.services);
        }
    }

}

// Create global message handler instance
window.messageHandler = new MessageHandler();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MessageHandler;
}
