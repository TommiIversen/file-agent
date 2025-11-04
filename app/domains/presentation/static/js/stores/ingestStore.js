/**
 * Ingest Store - Just In Engine Channel State Management
 *
 * Centralized state for monitoring Just In Engine ingest channels,
 * recording status, signal availability, and error conditions.
 * Integrates with Alpine.js store pattern for reactive UI updates.
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('ingest', {
        // Channel State
        channels: new Map(),           // Map<channelName, ChannelStatus>
        lastUpdate: null,             // Last update timestamp
        isConnected: false,           // Connection status to Just In Engine

        // Statistics
        statistics: {
            totalChannels: 0,
            recordingChannels: 0,
            errorChannels: 0,
            signalLostChannels: 0
        },

        // Error Log
        errors: [],                   // Array of recent channel errors
        MAX_ERRORS: 50,              // Maximum errors to keep in memory

        // Initialization
        init() {
            console.log('🎥 Ingest Store initialized');
            this.loadInitialData();
        },

        // Load initial data from API
        async loadInitialData() {
            try {
                console.log('📡 Fetching initial ingest status...');
                const response = await fetch('/api/ingest/status');
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                const data = await response.json();
                this.updateChannels(data);
                this.isConnected = true;
                console.log('✅ Initial ingest data loaded:', Object.keys(data).length, 'channels');
                
            } catch (error) {
                console.error('❌ Failed to load initial ingest data:', error);
                this.isConnected = false;
            }
        },

        // Update all channel data
        updateChannels(channelsData) {
            this.channels.clear();
            
            Object.entries(channelsData).forEach(([channelName, channelData]) => {
                this.channels.set(channelName, {
                    name: channelName,
                    is_recording: channelData.is_recording || false,
                    has_signal: channelData.has_signal !== undefined ? channelData.has_signal : true,
                    has_errors: channelData.has_errors || false,
                    last_errors: channelData.last_errors || [],
                    frames: channelData.frames || 0,
                    hours: channelData.hours || 0,
                    minutes: channelData.minutes || 0,
                    seconds: channelData.seconds || 0,
                    last_update: new Date().toISOString()
                });
            });

            this.lastUpdate = new Date().toISOString();
            this.updateStatistics();
            console.log(`📊 Updated ${this.channels.size} channels`);
        },

        // Update individual channel
        updateChannel(channelName, channelData) {
            const existing = this.channels.get(channelName) || {};
            
            this.channels.set(channelName, {
                ...existing,
                ...channelData,
                last_update: new Date().toISOString()
            });

            this.lastUpdate = new Date().toISOString();
            this.updateStatistics();
        },

        // Add channel error to log
        addChannelError(channelName, errorMessage, errorCode) {
            const error = {
                id: Date.now() + Math.random(), // Simple unique ID
                channel_name: channelName,
                error_message: errorMessage,
                error_code: errorCode,
                timestamp: new Date().toISOString(),
                severity: this.getErrorSeverity(errorCode)
            };

            this.errors.unshift(error); // Add to beginning of array

            // Maintain max errors limit
            if (this.errors.length > this.MAX_ERRORS) {
                this.errors.splice(this.MAX_ERRORS);
            }

            // Update channel error status
            const channel = this.channels.get(channelName);
            if (channel) {
                channel.has_errors = true;
                channel.last_error = error;
            }

            this.updateStatistics();
            console.log(`⚠️ Error added for channel ${channelName}: ${errorMessage}`);
        },

        // Determine error severity based on error code
        getErrorSeverity(errorCode) {
            if (!errorCode) return 'info';
            
            // Based on typical Just In Engine error codes
            if (errorCode === -8995) return 'warning'; // No signal
            if (errorCode < -9000) return 'critical';   // Critical errors
            if (errorCode < 0) return 'warning';        // Warning errors
            return 'info';                              // Info/status codes
        },

        // Update statistics
        updateStatistics() {
            const channels = Array.from(this.channels.values());
            
            this.statistics = {
                totalChannels: channels.length,
                recordingChannels: channels.filter(c => c.is_recording).length,
                errorChannels: channels.filter(c => c.has_errors).length,
                signalLostChannels: channels.filter(c => !c.has_signal).length
            };
        },

        // Get channels as array for iteration
        getChannelsArray() {
            return Array.from(this.channels.values());
        },

        // Get channels sorted by recording status (recording first)
        getChannelsSorted() {
            return this.getChannelsArray().sort((a, b) => {
                // Recording channels first
                if (a.is_recording && !b.is_recording) return -1;
                if (!a.is_recording && b.is_recording) return 1;
                
                // Then by channel name
                return a.name.localeCompare(b.name);
            });
        },

        // Get recording status summary for tally light logic
        getRecordingStatus() {
            const total = this.statistics.totalChannels;
            const recording = this.statistics.recordingChannels;
            
            if (recording === 0) return 'none';      // No recording
            if (recording === total) return 'all';   // All recording (solid)
            return 'some';                           // Some recording (blinking)
        },

        // Get recent errors (last 10)
        getRecentErrors() {
            return this.errors.slice(0, 10);
        },

        // Clear all errors
        clearErrors() {
            this.errors = [];
            
            // Clear error status from all channels
            this.channels.forEach(channel => {
                channel.has_errors = false;
                delete channel.last_error;
            });
            
            this.updateStatistics();
            console.log('🧹 All channel errors cleared');
        },

        // Get channel by name
        getChannel(channelName) {
            return this.channels.get(channelName);
        },

        // Format timecode for display
        formatTimecode(hours, minutes, seconds, frames) {
            const h = String(hours || 0).padStart(2, '0');
            const m = String(minutes || 0).padStart(2, '0');
            const s = String(seconds || 0).padStart(2, '0');
            const f = String(frames || 0).padStart(2, '0');
            return `${h}:${m}:${s}:${f}`;
        },

        // Format duration for display
        formatDuration(hours, minutes, seconds) {
            if (hours > 0) {
                return `${hours}h ${minutes}m ${seconds}s`;
            } else if (minutes > 0) {
                return `${minutes}m ${seconds}s`;
            } else {
                return `${seconds}s`;
            }
        },

        // Connection status management
        setConnected(connected) {
            this.isConnected = connected;
            if (!connected) {
                console.log('📡 Connection to Just In Engine lost');
            } else {
                console.log('📡 Connected to Just In Engine');
            }
        }
    });
});