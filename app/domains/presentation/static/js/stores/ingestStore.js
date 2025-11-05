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
        isClearing: false,           // State for clear operation
        isStarting: false,           // State for start all operation
        isStopping: false,           // State for stop all operation

        // Recording Timer
        recordingTimer: {
            isRunning: false,        // Whether any channel is recording
            startTime: null,         // When recording started
            currentTime: null,       // Current timer value
            intervalId: null,        // Interval timer ID
            displayTime: '00:00:00:00'  // Formatted display time with frames
        },

        // Initialization
        init() {
            console.log('🎥 Ingest Store initialized');
            this.loadInitialData();
            this.initRecordingTimer();
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

            // Update recording timer state
            this.updateRecordingTimer();
        },

        // Initialize recording timer
        initRecordingTimer() {
            console.log('⏱️ Recording timer initialized');
            this.recordingTimer.displayTime = '00:00:00:00';
        },

        // Update recording timer based on channel states
        updateRecordingTimer() {
            const recordingChannels = Array.from(this.channels.values()).filter(c => c.is_recording);
            const isRecording = recordingChannels.length > 0;

            if (isRecording && !this.recordingTimer.isRunning) {
                // Start timer - find channel with lowest time (newest recording)
                const minTimeChannel = recordingChannels.reduce((min, channel) => {
                    const channelTotalSeconds = (channel.hours || 0) * 3600 + (channel.minutes || 0) * 60 + (channel.seconds || 0);
                    const minTotalSeconds = (min.hours || 0) * 3600 + (min.minutes || 0) * 60 + (min.seconds || 0);
                    return channelTotalSeconds < minTotalSeconds ? channel : min;
                });
                
                this.startRecordingTimer(minTimeChannel);
            } else if (!isRecording && this.recordingTimer.isRunning) {
                // Stop timer
                this.stopRecordingTimer();
            } else if (isRecording && this.recordingTimer.isRunning) {
                // Sync timer with current channel time (find minimum time again)
                const minTimeChannel = recordingChannels.reduce((min, channel) => {
                    const channelTotalSeconds = (channel.hours || 0) * 3600 + (channel.minutes || 0) * 60 + (channel.seconds || 0);
                    const minTotalSeconds = (min.hours || 0) * 3600 + (min.minutes || 0) * 60 + (min.seconds || 0);
                    return channelTotalSeconds < minTotalSeconds ? channel : min;
                });
                
                this.syncRecordingTimer(minTimeChannel);
            }
        },

        // Start recording timer
        startRecordingTimer(baseChannel) {
            if (this.recordingTimer.intervalId) {
                clearInterval(this.recordingTimer.intervalId);
            }

            // Calculate start time based on channel's current time
            const channelTotalSeconds = (baseChannel.hours || 0) * 3600 + (baseChannel.minutes || 0) * 60 + (baseChannel.seconds || 0);
            this.recordingTimer.startTime = Date.now() - (channelTotalSeconds * 1000);
            this.recordingTimer.isRunning = true;

            // Start live counter at 25fps (40ms intervals for frame accuracy)
            this.recordingTimer.intervalId = setInterval(() => {
                this.updateTimerDisplay();
            }, 40);

            console.log(`⏱️ Recording timer started, synced to channel: ${baseChannel.name} (${channelTotalSeconds}s)`);
            this.updateTimerDisplay();
        },

        // Stop recording timer
        stopRecordingTimer() {
            if (this.recordingTimer.intervalId) {
                clearInterval(this.recordingTimer.intervalId);
                this.recordingTimer.intervalId = null;
            }

            this.recordingTimer.isRunning = false;
            this.recordingTimer.startTime = null;
            this.recordingTimer.currentTime = null;
            this.recordingTimer.displayTime = '00:00:00:00';

            console.log('⏱️ Recording timer stopped');
        },

        // Sync timer with channel time (update start time to match)
        syncRecordingTimer(baseChannel) {
            const channelTotalSeconds = (baseChannel.hours || 0) * 3600 + (baseChannel.minutes || 0) * 60 + (baseChannel.seconds || 0);
            const newStartTime = Date.now() - (channelTotalSeconds * 1000);
            
            // Only update if there's a significant difference (more than 2 seconds)
            if (!this.recordingTimer.startTime || Math.abs(newStartTime - this.recordingTimer.startTime) > 2000) {
                this.recordingTimer.startTime = newStartTime;
                console.log(`⏱️ Recording timer synced to channel: ${baseChannel.name} (${channelTotalSeconds}s)`);
            }
        },

        // Update timer display with frame precision (25fps)
        updateTimerDisplay() {
            if (!this.recordingTimer.isRunning || !this.recordingTimer.startTime) {
                this.recordingTimer.displayTime = '00:00:00:00';
                return;
            }

            const elapsedMs = Date.now() - this.recordingTimer.startTime;
            
            // Calculate total frames elapsed (25fps)
            const totalFrames = Math.floor((elapsedMs * 25) / 1000);
            
            // Break down into hours, minutes, seconds, frames
            const hours = Math.floor(totalFrames / (25 * 60 * 60));
            const minutes = Math.floor((totalFrames % (25 * 60 * 60)) / (25 * 60));
            const seconds = Math.floor((totalFrames % (25 * 60)) / 25);
            const frames = totalFrames % 25;

            this.recordingTimer.displayTime = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}:${String(frames).padStart(2, '0')}`;
            this.recordingTimer.currentTime = { hours, minutes, seconds, frames };
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

        // Clear all errors via API
        async clearAllErrors() {
            if (this.isClearing) {
                console.log('🔄 Clear operation already in progress');
                return;
            }

            this.isClearing = true;
            
            try {
                console.log('🗑️ Clearing all channel errors via API...');
                const response = await fetch('/api/ingest/clear-all-errors', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    }
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                const result = await response.json();
                
                if (result.success) {
                    // Clear local error state
                    this.clearErrors();
                    
                    console.log(`✅ ${result.message}`);
                    console.log(`📊 Cleared errors for ${result.channels_cleared}/${result.total_channels} channels`);
                    
                    // Show success message to user (you could add a toast notification here)
                    // For now, just log it
                    
                } else {
                    throw new Error(result.message || 'Unknown error occurred');
                }
                
            } catch (error) {
                console.error('❌ Failed to clear all errors:', error);
                // You could show an error toast here
                
            } finally {
                this.isClearing = false;
            }
        },

        // Start all channels via API
        async startAllChannels() {
            if (this.isStarting) {
                console.log('🔄 Start operation already in progress');
                return;
            }

            this.isStarting = true;
            
            try {
                console.log('▶️ Starting all channels via API...');
                const response = await fetch('/api/ingest/start-all-channels', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    }
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                const result = await response.json();
                
                if (result.success) {
                    console.log(`✅ ${result.message}`);
                    console.log(`📊 Started ${result.channels_started}/${result.total_channels} channels`);
                    
                    // Refresh data to get updated channel states
                    setTimeout(() => this.loadInitialData(), 1000);
                    
                } else {
                    throw new Error(result.message || 'Unknown error occurred');
                }
                
            } catch (error) {
                console.error('❌ Failed to start all channels:', error);
                
            } finally {
                this.isStarting = false;
            }
        },

        // Stop all channels via API
        async stopAllChannels() {
            if (this.isStopping) {
                console.log('🔄 Stop operation already in progress');
                return;
            }

            this.isStopping = true;
            
            try {
                console.log('⏸️ Stopping all channels via API...');
                const response = await fetch('/api/ingest/stop-all-channels', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    }
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                const result = await response.json();
                
                if (result.success) {
                    console.log(`✅ ${result.message}`);
                    console.log(`📊 Stopped ${result.channels_stopped}/${result.total_channels} channels`);
                    
                    // Refresh data to get updated channel states
                    setTimeout(() => this.loadInitialData(), 1000);
                    
                } else {
                    throw new Error(result.message || 'Unknown error occurred');
                }
                
            } catch (error) {
                console.error('❌ Failed to stop all channels:', error);
                
            } finally {
                this.isStopping = false;
            }
        },

        // Get channel by name
        getChannel(channelName) {
            return this.channels.get(channelName);
        },

        // Format timecode for display (with frames)
        formatTimecode(hours, minutes, seconds, frames) {
            const h = String(hours || 0).padStart(2, '0');
            const m = String(minutes || 0).padStart(2, '0');
            const s = String(seconds || 0).padStart(2, '0');
            const f = String(frames || 0).padStart(2, '0');
            return `${h}:${m}:${s}:${f}`;
        },

        // Format duration for display (with frames)
        formatDuration(hours, minutes, seconds, frames) {
            if (hours > 0) {
                return `${hours}h ${minutes}m ${seconds}s ${frames}f`;
            } else if (minutes > 0) {
                return `${minutes}m ${seconds}s ${frames}f`;
            } else {
                return `${seconds}s ${frames}f`;
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
        },

        // Cleanup function (called when component is destroyed)
        cleanup() {
            if (this.recordingTimer.intervalId) {
                clearInterval(this.recordingTimer.intervalId);
                this.recordingTimer.intervalId = null;
            }
            console.log('🧹 Ingest store cleaned up');
        }
    });
});