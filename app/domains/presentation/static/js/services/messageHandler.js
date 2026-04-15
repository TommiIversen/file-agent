/**
 * Message Handler Service - WebSocket Message Processing
 *
 * Centralized message routing and processing for WebSocket messages.
 * Routes messages to appropriate stores and handles different message types.
 */

class MessageHandler {
    constructor() {
        /** @type {FileStore | null} */
        this.fileStore = null;
        /** @type {StorageStore | null} */
        this.storageStore = null;
        /** @type {ConnectionStore | null} */
        this.connectionStore = null;
        /** @type {IngestStore | null} */
        this.ingestStore = null;
        /** @type {any[]} */
        this.messageQueue = [];

        // Initialize after Alpine is ready
        document.addEventListener('alpine:init', () => {
            // Use $nextTick to ensure all stores are ready
            Alpine.nextTick(() => {
                this.fileStore = /** @type {FileStore | null} */ (Alpine.store('files'));
                this.storageStore = /** @type {StorageStore | null} */ (Alpine.store('storage'));
                this.connectionStore = /** @type {ConnectionStore | null} */ (Alpine.store('connection'));
                this.ingestStore = /** @type {IngestStore | null} */ (Alpine.store('ingest'));
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
     * @param {any} message
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

                case 'ingest_status_update':
                    this.handleIngestStatusUpdate(message.data);
                    break;

                case 'channel_error':
                    this.handleChannelError(message.data);
                    break;

                case 'tally_switch_status_update':
                    this.handleTallySwitchStatusUpdate(message.data);
                    break;

                case 'tally_switch_online':
                    this.handleTallySwitchStatusUpdate(message.data);
                    break;

                case 'tally_switch_offline':
                    this.handleTallySwitchStatusUpdate(message.data);
                    break;

                case 'ingest_online':
                    this.handleIngestConnectionChange(message.data);
                    break;

                case 'ingest_offline':
                    this.handleIngestConnectionChange(message.data);
                    break;

                case 'recording_paths_update':
                    this.handleRecordingPathsUpdate(message.data);
                    break;

                case 'auto_stop_warning':
                    this.handleAutoStopWarning(message.data);
                    break;

                case 'auto_stop_triggered':
                    this.handleAutoStopTriggered(message.data);
                    break;

                case 'audio_recording_started':
                    Alpine.store('audio')?.handleStarted(message.data);
                    break;

                case 'audio_recording_stopped':
                    Alpine.store('audio')?.handleStopped(message.data);
                    break;

                case 'audio_recording_error':
                    Alpine.store('audio')?.handleError(message.data);
                    break;

                case 'audio_device_disconnected':
                    Alpine.store('audio')?.handleDeviceDisconnected(message.data);
                    break;

                case 'audio_overflow_warning':
                    Alpine.store('audio')?.handleOverflowWarning(message.data);
                    break;

                case 'audio_levels':
                    Alpine.store('audio')?.updateLevels(message.data);
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
     * @param {{files: TrackedFile[], statistics: FileStore['statistics'], storage: { source: StorageInfo, destination: StorageInfo, overall_status: StorageStatus }, scanner: ScannerStatus}} data
     */
    handleInitialState(data) {
        console.log('Received initial state:', data);

        // Update files
        if (data.files && Array.isArray(data.files)) {
            this.fileStore?.setInitialFiles(data.files);
        }

        // Update statistics
        if (data.statistics) {
            this.fileStore?.updateStatistics(data.statistics);
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
                if (this.storageStore) {
                    this.storageStore.overall_status = data.storage.overall_status;
                }
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

        // Update tally switch status if available
        // Cast to any to avoid TypeScript errors
        const anyData = /** @type {any} */ (data);
        
        if (anyData.tally_switch) {
            const tallySwitchStore = Alpine.store('tallySwitch');
            if (tallySwitchStore) {
                tallySwitchStore.loadInitialData(anyData);
            }
            console.log('Tally switch status loaded from initial state:', anyData.tally_switch);
        }

        // Update ingest connection status if available
        if (anyData.ingest_connection) {
            if (this.ingestStore) {
                this.ingestStore.loadInitialState(anyData);
            }
            console.log('Ingest connection status loaded from initial state:', anyData.ingest_connection);
        }

        console.log(`Initial state loaded: ${data.files?.length || 0} files`);
    }

    /**
     * Handle individual file updates
     * @param {{file: TrackedFile}} data
     */
    handleFileUpdate(data) {
        console.log('File update received:', data.file.file_path);

        if (!data.file || !data.file.id) {
            console.warn('Invalid file update data - missing file ID:', data);
            return;
        }

        // Update or add file using ID instead of file_path
        this.fileStore?.updateFile(data.file.id, data.file);

        // Log significant status changes
        if (data.file.status) {
            console.log(`File ${data.file.file_path} (ID: ${data.file.id}) status: ${data.file.status}`);
        }
    }

    /**
     * Handle newly discovered files
     * @param {{file_path: string, file_size: number, file_size_mb: number, status: FileStatus, last_write_time: string, timestamp: string}} data
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
            id: `temp_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`, // Assign a temporary ID
            copy_progress: 0,
            bytes_copied: 0,
            error_message: null,
            retry_count: 0,
            creation_time: null,
            started_copying_at: null,
            completed_at: null,
            failed_at: null,
            space_error_at: null,
            destination_path: null,
            growth_rate_mbps: 0,
            copy_speed_mbps: 0,
            last_growth_check: null,
            previous_file_size: 0,
            first_seen_size: 0,
            growth_stable_since: null,
            retry_info: null,
            isDiscovered: true
        };

        // Add to file store as a discovered file
        this.fileStore?.addDiscoveredFile(discoveredFile);

        console.log(`File discovered: ${data.file_path} (${data.file_size_mb} MB)`);
    }

    /**
     * Handle file progress updates
     * @param {{file_id: string, progress_percent: number, bytes_copied: number, total_bytes: number, copy_speed_mbps: number, is_final: boolean}} data
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
     * @param {{file_path: string, file_id: string, bytes_copied: number, destination_path: string, is_growing_file: boolean, source_size: number, dest_size: number}} data
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
     * @param {{statistics: FileStore['statistics']}} data
     */
    handleStatisticsUpdate(data) {
        console.log('Statistics update received');

        if (data.statistics) {
            this.fileStore?.updateStatistics(data.statistics);
        }
    }

    /**
     * Handle storage updates
     * @param {StorageUpdateData} data
     */
    handleStorageUpdate(data) {
        console.log('Storage update received:', data.storage_type);

        this.storageStore?.handleStorageUpdate(data);
    }

    /**
     * Handle mount status updates
     * @param {MountStatusUpdateData} data
     */
    handleMountStatus(data) {
        console.log('Mount status update received:', data.storage_type, data.mount_status);

        this.storageStore?.handleMountStatus(data);
    }

    /**
     * Handle scanner status updates
     * @param {ScannerStatus} data
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
     * @param {{overall_health: string, services: any}} data
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

    /**
     * Handle ingest status updates from Just In Engine
     * @param {{channels: {[key: string]: ChannelStatus}, auto_stop?: Object}} data
     */
    handleIngestStatusUpdate(data) {
        if (!this.ingestStore) {
            console.warn('IngestStore not available for ingest status update');
            return;
        }

        console.log('📡 Ingest status update received:', Object.keys(data.channels || {}).length, 'channels');
        
        if (data.channels) {
            this.ingestStore.updateChannels(data.channels);
            this.ingestStore.setConnected(true);
        }

        // Update auto-stop state (included in every status broadcast)
        if (data.auto_stop) {
            this.ingestStore.updateAutoStop(data.auto_stop);
        }
    }

    /**
     * Handle channel error events from Just In Engine
     * @param {ChannelError} data
     */
    handleChannelError(data) {
        if (!this.ingestStore) {
            console.warn('IngestStore not available for channel error');
            return;
        }

        console.log('⚠️ Channel error received:', data.channel_name, '-', data.error_message);
        
        this.ingestStore.addChannelError(
            data.channel_name,
            data.error_message,
            data.error_code
        );
    }

    /**
     * Handle tally switch status update
     * @param {Object} data - Tally switch status data
     */
    handleTallySwitchStatusUpdate(data) {
        console.log('🔄 Tally switch status update received:', data);
        
        // Get tally switch store and update status
        const tallySwitchStore = window.Alpine?.store('tallySwitch');
        if (tallySwitchStore) {
            tallySwitchStore.updateStatus(data);
        } else {
            console.warn('TallySwitch store not found');
        }
    }

    /**
     * Handle ingest connection status changes
     * @param {Object} data - Ingest connection status data
     */
    handleIngestConnectionChange(data) {
        console.log('Ingest connection status update received:', data);
        
        if (this.ingestStore) {
            this.ingestStore.setConnected(data.is_connected);
        } else {
            console.warn('IngestStore not available for connection status update');
        }
    }

    /**
     * Handle recording paths discovered from Just In Engine
     * @param {{channel_name: string, preset_name: string, paths: string[]}} data
     */
    handleRecordingPathsUpdate(data) {
        if (!this.ingestStore) {
            console.warn('IngestStore not available for recording paths update');
            return;
        }

        console.log(`Recording paths update for ${data.channel_name}:`, data.paths);
        this.ingestStore.updateRecordingPaths(
            data.channel_name,
            data.preset_name,
            data.paths
        );
    }

    /**
     * Handle auto-stop warning from server
     * @param {{channel_name: string, recording_seconds: number, limit_seconds: number, remaining_seconds: number}} data
     */
    handleAutoStopWarning(data) {
        if (!this.ingestStore) return;
        const remainMin = Math.floor(data.remaining_seconds / 60);
        console.warn(`⏱️ AUTO-STOP WARNING: ${remainMin}m remaining (channel ${data.channel_name})`);
        this.ingestStore.autoStop.warningSent = true;
    }

    /**
     * Handle auto-stop triggered from server
     * @param {{channel_name: string, recording_seconds: number, limit_seconds: number}} data
     */
    handleAutoStopTriggered(data) {
        if (!this.ingestStore) return;
        console.warn(`🛑 AUTO-STOP TRIGGERED: Stopping all channels (channel ${data.channel_name} at ${data.recording_seconds}s)`);
        this.ingestStore.autoStop.triggered = true;
    }

}

// Create global message handler instance
window.messageHandler = new MessageHandler();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MessageHandler;
}
