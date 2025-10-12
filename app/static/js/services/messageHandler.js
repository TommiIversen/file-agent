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
        
        // Initialize after Alpine is ready
        document.addEventListener('alpine:init', () => {
            // Wait for stores to be available
            setTimeout(() => {
                this.fileStore = Alpine.store('files');
                this.storageStore = Alpine.store('storage');
                this.connectionStore = Alpine.store('connection');
                console.log('MessageHandler initialized with stores');
            }, 100);
        });
    }
    
    /**
     * Main message handler - routes messages by type
     */
    handleMessage(message) {
        if (!message || !message.type) {
            console.warn('Invalid message received:', message);
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
                    
                case 'statistics_update':
                    this.handleStatisticsUpdate(message.data);
                    break;
                    
                case 'storage_update':
                    this.handleStorageUpdate(message.data);
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
        
        if (!this.fileStore) {
            console.error('FileStore not available for initial state');
            return;
        }
        
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
        
        console.log(`Initial state loaded: ${data.files?.length || 0} files`);
    }
    
    /**
     * Handle individual file updates
     */
    handleFileUpdate(data) {
        console.log('File update received:', data.file_path);
        
        if (!this.fileStore) {
            console.error('FileStore not available for file update');
            return;
        }
        
        if (!data.file_path || !data.file) {
            console.warn('Invalid file update data:', data);
            return;
        }
        
        // Update or add file
        this.fileStore.updateFile(data.file_path, data.file);
        
        // Log significant status changes
        if (data.file.status) {
            console.log(`File ${data.file_path} status: ${data.file.status}`);
        }
    }
    
    /**
     * Handle statistics updates
     */
    handleStatisticsUpdate(data) {
        console.log('Statistics update received');
        
        if (!this.fileStore) {
            console.error('FileStore not available for statistics update');
            return;
        }
        
        if (data.statistics) {
            this.fileStore.updateStatistics(data.statistics);
        }
    }
    
    /**
     * Handle storage updates
     */
    handleStorageUpdate(data) {
        console.log('Storage update received:', data.storage_type);
        
        if (!this.storageStore) {
            console.error('StorageStore not available for storage update');
            return;
        }
        
        this.storageStore.handleStorageUpdate(data);
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