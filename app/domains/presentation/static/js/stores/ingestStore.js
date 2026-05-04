// @ts-check


document.addEventListener('alpine:init', () => {
    Alpine.store('ingest', {
        // === STATE ===

        /** @type {Map<string, ChannelStatus>} */
        channels: new Map(),
        /** @type {string|null} */
        lastUpdate: null,
        /** @type {boolean} */
        isConnected: false,

        /** Statistics about the channels. */
        statistics: {
            /** @type {number} */
            totalChannels: 0,
            /** @type {number} */
            recordingChannels: 0,
            /** @type {number} */
            errorChannels: 0,
            /** @type {number} */
            signalLostChannels: 0
        },

        /** @type {ChannelError[]} */
        errors: [],
        /** @type {number} */
        MAX_ERRORS: 50,
        /** @type {boolean} */
        isClearing: false,
        /** @type {boolean} */
        isStarting: false,
        /** @type {boolean} */
        isStopping: false,

        /** State for the master recording timer. */
        recordingTimer: {
            /** @type {boolean} */
            isRunning: false,
            /** @type {number|null} */
            startTime: null,
            /** @type {RecordingTime|null} */
            currentTime: null,
            /** @type {number|null} */
            intervalId: null,
            /** @type {string} */
            displayTime: '00:00:00:00'
        },

        /** @type {Object.<string, {preset_name: string, paths: string[]}>} */
        recordingPaths: {},

        /** Auto-stop state - populated from server every 2s. */
        autoStop: {
            /** @type {boolean} */
            enabled: false,
            /** @type {number} */
            limitSeconds: 0,
            /** @type {number} */
            warningSeconds: 0,
            /** @type {boolean} */
            warningSent: false,
            /** @type {boolean} */
            triggered: false,
            /** @type {number} */
            maxRecordingSeconds: 0,
            /** @type {number} */
            remainingSeconds: 0,
        },

        /** @type {string} Client-side interpolated countdown display (HH:MM:SS:FF). */
        countdownDisplayTime: '00:00:00:00',
        /** @type {number} Server-provided remaining seconds at last sync. */
        _countdownServerRemaining: 0,
        /** @type {number|null} Timestamp (ms) when remainingSeconds was last received from server. */
        _countdownLastUpdate: null,

        // === METHODS ===

        /**
         * Initializes the store by loading initial data and setting up timers.
         */
        init() {
            console.log('Ingest Store initialized');
            this.loadInitialData();
            this.initRecordingTimer();
            this.loadRecordingPaths();
        },

        /**
         * Fetches the initial state of all ingest channels from the API.
         * @returns {Promise<void>}
         */
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

        /**
         * Updates the entire set of channels from a data object.
         * @param {Object.<string, Partial<ChannelStatus>>} channelsData - An object where keys are channel names.
         */
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

        /**
         * Set the connection status for the ingest monitor.
         * @param {boolean} connected - True if connected to Just In Engine
         */
        setConnected(connected) {
            if (this.isConnected !== connected) {
                this.isConnected = connected;
                console.log(`📡 Ingest connection status: ${connected ? 'CONNECTED' : 'DISCONNECTED'}`);
                
                // Stop recording timer when disconnected
                if (!connected) {
                    this.stopRecordingTimer();
                    console.log('🛑 Recording timer stopped due to connection loss');
                }
            }
        },

        /**
         * Handle initial state loading including connection status.
         * @param {{ingest_connection?: {is_connected: boolean}, channels?: Object.<string, Partial<ChannelStatus>>}} initialData
         */
        loadInitialState(initialData) {
            // Load connection status if provided
            if (initialData.ingest_connection) {
                this.setConnected(initialData.ingest_connection.is_connected);
            }
            
            // Load channel data if available
            if (initialData.channels) {
                this.updateChannels(initialData.channels);
            }
        },

        /**
         * Get connection status color for UI indicators.
         * @returns {string} Tailwind CSS color class
         */
        getConnectionStatusColor() {
            return this.isConnected ? 'bg-green-500' : 'bg-red-500';
        },

        /**
         * Get connection status text.
         * @returns {string} Human-readable connection status
         */
        getConnectionStatusText() {
            return this.isConnected ? 'Just In Engine: Online' : 'Just In Engine: Offline';
        },

        /**
         * Updates a single channel with new data.
         * @param {string} channelName - The name of the channel to update.
         * @param {Partial<ChannelStatus>} channelData - The new data for the channel.
         */
        updateChannel(channelName, channelData) {
            const existing = this.channels.get(channelName);
            
            this.channels.set(channelName, {
                ...existing,
                ...channelData,
                name: channelName, // Ensure name is always set
                is_recording: channelData.is_recording ?? existing?.is_recording ?? false,
                has_signal: channelData.has_signal ?? existing?.has_signal ?? true,
                has_errors: channelData.has_errors ?? existing?.has_errors ?? false,
                last_errors: channelData.last_errors ?? existing?.last_errors ?? [],
                frames: channelData.frames ?? existing?.frames ?? 0,
                hours: channelData.hours ?? existing?.hours ?? 0,
                minutes: channelData.minutes ?? existing?.minutes ?? 0,
                seconds: channelData.seconds ?? existing?.seconds ?? 0,
                last_update: new Date().toISOString()
            });

            this.lastUpdate = new Date().toISOString();
            this.updateStatistics();
        },

        /**
         * Adds a new channel error to the log and updates the channel's state.
         * @param {string} channelName - The name of the channel.
         * @param {string} errorMessage - The error message.
         * @param {any} errorCode - The error code.
         */
        addChannelError(channelName, errorMessage, errorCode) {
            /** @type {ChannelError} */
            const error = {
                id: Date.now() + Math.random(),
                channel_name: channelName,
                error_message: errorMessage,
                error_code: errorCode,
                timestamp: new Date().toISOString(),
                severity: this.getErrorSeverity(errorCode)
            };

            this.errors.unshift(error);

            if (this.errors.length > this.MAX_ERRORS) {
                this.errors.splice(this.MAX_ERRORS);
            }

            const channel = this.channels.get(channelName);
            if (channel) {
                channel.has_errors = true;
                channel.last_error = error;
            }

            this.updateStatistics();
            console.log(`⚠️ Error added for channel ${channelName}: ${errorMessage}`);
        },

        /**
         * Determines the severity of an error based on its code.
         * @param {any} errorCode - The error code.
         * @returns {ErrorSeverity}
         */
        getErrorSeverity(errorCode) {
            if (!errorCode) return 'info';
            const code = Number(errorCode);
            if (code === -8995) return 'warning';
            if (code < -9000) return 'critical';
            if (code < 0) return 'warning';
            return 'info';
        },

        /**
         * Recalculates all statistics based on the current channel states.
         */
        updateStatistics() {
            const channels = Array.from(this.channels.values());
            
            this.statistics = {
                totalChannels: channels.length,
                recordingChannels: channels.filter((/** @type {ChannelStatus} */ c) => c.is_recording).length,
                errorChannels: channels.filter((/** @type {ChannelStatus} */ c) => c.has_errors).length,
                signalLostChannels: channels.filter((/** @type {ChannelStatus} */ c) => !c.has_signal).length
            };

            this.updateRecordingTimer();
        },

        /**
         * Initializes the recording timer display.
         */
        initRecordingTimer() {
            console.log('⏱️ Recording timer initialized');
            this.recordingTimer.displayTime = '00:00:00:00';
        },

        /**
         * Starts, stops, or syncs the master recording timer based on channel states.
         */
        updateRecordingTimer() {
            const recordingChannels = Array.from(this.channels.values()).filter((/** @type {ChannelStatus} */ c) => c.is_recording);
            const isRecording = recordingChannels.length > 0;

            if (isRecording && !this.recordingTimer.isRunning) {
                const minTimeChannel = recordingChannels.reduce((/** @type {ChannelStatus} */ min, /** @type {ChannelStatus} */ channel) => {
                    const channelTotalSeconds = (channel.hours || 0) * 3600 + (channel.minutes || 0) * 60 + (channel.seconds || 0);
                    const minTotalSeconds = (min.hours || 0) * 3600 + (min.minutes || 0) * 60 + (min.seconds || 0);
                    return channelTotalSeconds < minTotalSeconds ? channel : min;
                });
                this.startRecordingTimer(minTimeChannel);
            } else if (!isRecording && this.recordingTimer.isRunning) {
                this.stopRecordingTimer();
                this._countdownServerRemaining = 0;
                this._countdownLastUpdate = null;
                this.countdownDisplayTime = '00:00:00:00';
            } else if (isRecording && this.recordingTimer.isRunning) {
                const minTimeChannel = recordingChannels.reduce((/** @type {ChannelStatus} */ min, /** @type {ChannelStatus} */ channel) => {
                    const channelTotalSeconds = (channel.hours || 0) * 3600 + (channel.minutes || 0) * 60 + (channel.seconds || 0);
                    const minTotalSeconds = (min.hours || 0) * 3600 + (min.minutes || 0) * 60 + (min.seconds || 0);
                    return channelTotalSeconds < minTotalSeconds ? channel : min;
                });
                this.syncRecordingTimer(minTimeChannel);
            }
        },

        /**
         * Starts the master recording timer, syncing to a base channel.
         * @param {ChannelStatus} baseChannel - The channel to sync the timer with.
         */
        startRecordingTimer(baseChannel) {
            if (this.recordingTimer.intervalId) {
                clearInterval(this.recordingTimer.intervalId);
            }

            const channelTotalSeconds = (baseChannel.hours || 0) * 3600 + (baseChannel.minutes || 0) * 60 + (baseChannel.seconds || 0);
            this.recordingTimer.startTime = Date.now() - (channelTotalSeconds * 1000);
            this.recordingTimer.isRunning = true;

            this.recordingTimer.intervalId = window.setInterval(() => {
                this.updateTimerDisplay();
            }, 40);

            console.log(`⏱️ Recording timer started, synced to channel: ${baseChannel.name} (${channelTotalSeconds}s)`);
            this.updateTimerDisplay();
        },

        /**
         * Stops the master recording timer.
         */
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

        /**
         * Re-synchronizes the master timer with a base channel's time.
         * @param {ChannelStatus} baseChannel - The channel to sync with.
         */
        syncRecordingTimer(baseChannel) {
            const channelTotalSeconds = (baseChannel.hours || 0) * 3600 + (baseChannel.minutes || 0) * 60 + (baseChannel.seconds || 0);
            const newStartTime = Date.now() - (channelTotalSeconds * 1000);
            
            if (!this.recordingTimer.startTime || Math.abs(newStartTime - this.recordingTimer.startTime) > 2000) {
                this.recordingTimer.startTime = newStartTime;
                console.log(`⏱️ Recording timer synced to channel: ${baseChannel.name} (${channelTotalSeconds}s)`);
            }
        },

        /**
         * Updates the timer's display string based on elapsed time.
         * Also updates the auto-stop countdown display if active.
         */
        updateTimerDisplay() {
            if (!this.recordingTimer.isRunning || !this.recordingTimer.startTime) {
                this.recordingTimer.displayTime = '00:00:00:00';
                this.countdownDisplayTime = '00:00:00:00';
                return;
            }

            const now = Date.now();
            const elapsedMs = now - this.recordingTimer.startTime;
            const totalFrames = Math.floor((elapsedMs * 25) / 1000);
            
            const hours = Math.floor(totalFrames / (25 * 60 * 60));
            const minutes = Math.floor((totalFrames % (25 * 60 * 60)) / (25 * 60));
            const seconds = Math.floor((totalFrames % (25 * 60)) / 25);
            const frames = totalFrames % 25;

            this.recordingTimer.displayTime = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}:${String(frames).padStart(2, '0')}`;

            // Mutate in-place to avoid creating a new proxy object 25×/sec
            const ct = this.recordingTimer.currentTime;
            if (ct) {
                ct.hours = hours;
                ct.minutes = minutes;
                ct.seconds = seconds;
                ct.frames = frames;
            } else {
                this.recordingTimer.currentTime = { hours, minutes, seconds, frames };
            }

            // Interpolate auto-stop countdown with frame accuracy
            if (this.autoStop.enabled && this._countdownLastUpdate && this._countdownServerRemaining > 0) {
                const elapsedSinceSync = (now - this._countdownLastUpdate) / 1000;
                const remaining = Math.max(0, this._countdownServerRemaining - elapsedSinceSync);
                const cFrames = Math.floor(remaining * 25);
                const cH = Math.floor(cFrames / (25 * 60 * 60));
                const cM = Math.floor((cFrames % (25 * 60 * 60)) / (25 * 60));
                const cS = Math.floor((cFrames % (25 * 60)) / 25);
                const cF = cFrames % 25;
                this.countdownDisplayTime = `${String(cH).padStart(2, '0')}:${String(cM).padStart(2, '0')}:${String(cS).padStart(2, '0')}:${String(cF).padStart(2, '0')}`;
            } else if (this.autoStop.enabled) {
                this.countdownDisplayTime = '00:00:00:00';
            }
        },

        /**
         * Gets all channels as a simple array.
         * @returns {ChannelStatus[]}
         */
        getChannelsArray() {
            return Array.from(this.channels.values());
        },

        /**
         * Gets all channels sorted by recording status and then name.
         * @returns {ChannelStatus[]}
         */
        getChannelsSorted() {
            return this.getChannelsArray().sort((/** @type {ChannelStatus} */ a, /** @type {ChannelStatus} */ b) => {
                if (a.is_recording && !b.is_recording) return -1;
                if (!a.is_recording && b.is_recording) return 1;
                return a.name.localeCompare(b.name);
            });
        },

        /**
         * Gets a summary of the recording status for tally light logic.
         * Returns 'blink' when auto-stop warning is active (overrides normal state).
         * @returns {'none' | 'some' | 'all' | 'blink'}
         */
        getRecordingStatus() {
            const total = this.statistics.totalChannels;
            const recording = this.statistics.recordingChannels;
            if (recording === 0) return 'none';
            // Auto-stop warning forces blink regardless of channel count
            if (this.autoStop.warningSent && !this.autoStop.triggered) return 'blink';
            if (recording === total && total > 0) return 'all';
            return 'some';
        },

        /**
         * Gets the 10 most recent errors.
         * @returns {ChannelError[]}
         */
        getRecentErrors() {
            return this.errors.slice(0, 10);
        },

        /**
         * Clears all errors from the local state.
         */
        clearErrors() {
            this.errors = [];
            this.channels.forEach((/** @type {ChannelStatus} */ channel) => {
                channel.has_errors = false;
                delete channel.last_error;
            });
            this.updateStatistics();
            console.log('🧹 All channel errors cleared');
        },

        /**
         * Clears all channel errors via an API call.
         * @returns {Promise<void>}
         */
        async clearAllErrors() {
            if (this.isClearing) return;
            this.isClearing = true;
            try {
                console.log('🗑️ Clearing all channel errors via API...');
                const response = await fetch('/api/ingest/clear-all-errors', { method: 'POST' });
                if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                const result = await response.json();
                if (result.success) {
                    this.clearErrors();
                    console.log(`✅ ${result.message}`);
                } else {
                    throw new Error(result.message || 'Unknown error occurred');
                }
            } catch (error) {
                console.error('❌ Failed to clear all errors:', error);
            } finally {
                this.isClearing = false;
            }
        },

        /**
         * Starts all channels via an API call.
         * @returns {Promise<void>}
         */
        async startAllChannels() {
            if (this.isStarting) return;
            this.isStarting = true;
            try {
                console.log('▶️ Starting all channels via API...');
                const response = await fetch('/api/ingest/start-all-channels', { method: 'POST' });
                if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                const result = await response.json();
                if (result.success) {
                    console.log(`✅ ${result.message}`);
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

        /**
         * Stops all channels via an API call.
         * @returns {Promise<void>}
         */
        async stopAllChannels() {
            if (this.isStopping) return;
            this.isStopping = true;
            try {
                console.log('⏸️ Stopping all channels via API...');
                const response = await fetch('/api/ingest/stop-all-channels', { method: 'POST' });
                if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                const result = await response.json();
                if (result.success) {
                    console.log(`✅ ${result.message}`);
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

        /**
         * Gets a channel's status by its name.
         * @param {string} channelName - The name of the channel.
         * @returns {ChannelStatus|undefined}
         */
        getChannel(channelName) {
            return this.channels.get(channelName);
        },

        /**
         * Formats time parts into a timecode string.
         * @param {number} hours
         * @param {number} minutes
         * @param {number} seconds
         * @param {number} frames
         * @returns {string}
         */
        formatTimecode(hours, minutes, seconds, frames) {
            const h = String(hours || 0).padStart(2, '0');
            const m = String(minutes || 0).padStart(2, '0');
            const s = String(seconds || 0).padStart(2, '0');
            const f = String(frames || 0).padStart(2, '0');
            return `${h}:${m}:${s}:${f}`;
        },

        /**
         * Formats time parts into a duration string.
         * @param {number} hours
         * @param {number} minutes
         * @param {number} seconds
         * @param {number} frames
         * @returns {string}
         */
        formatDuration(hours, minutes, seconds, frames) {
            if (hours > 0) return `${hours}h ${minutes}m ${seconds}s ${frames}f`;
            if (minutes > 0) return `${minutes}m ${seconds}s ${frames}f`;
            return `${seconds}s ${frames}f`;
        },

        /**
         * Updates the recording destination paths for a channel.
         * @param {string} channelName - The channel name.
         * @param {string} presetName - The destination preset name.
         * @param {string[]} paths - The list of recording paths.
         */
        updateRecordingPaths(channelName, presetName, paths) {
            this.recordingPaths[channelName] = {
                preset_name: presetName,
                paths: paths
            };
            console.log(`Recording paths updated for ${channelName} (preset=${presetName}):`, paths);
        },

        /**
         * Fetches the initial recording paths from the API.
         * @returns {Promise<void>}
         */
        async loadRecordingPaths() {
            try {
                const response = await fetch('/api/ingest/recording-paths');
                if (!response.ok) return;
                const data = await response.json();
                // data is { "KAM_1": { "preset_name": "Default", "paths": ["/Volumes/NLE"] } }
                Object.entries(data).forEach(([channelName, info]) => {
                    this.recordingPaths[channelName] = info;
                });
                if (Object.keys(data).length > 0) {
                    console.log('Recording paths loaded:', Object.keys(data).length, 'channels');
                }
            } catch (/** @type {any} */ error) {
                // Not critical - paths may not be available yet
                console.debug('Recording paths not available yet:', error.message);
            }
        },

        /**
         * Gets the recording paths for a specific channel.
         * @param {string} channelName
         * @returns {{preset_name: string, paths: string[]}|null}
         */
        getRecordingPathsForChannel(channelName) {
            return this.recordingPaths[channelName] || null;
        },

        /**
         * Check if any recording paths have been discovered.
         * @returns {boolean}
         */
        hasRecordingPaths() {
            return Object.keys(this.recordingPaths).length > 0;
        },

        /**
         * Updates auto-stop state from the server payload.
         * @param {{enabled?: boolean, limit_seconds?: number, warning_seconds?: number, warning_sent?: boolean, triggered?: boolean, max_recording_seconds?: number, remaining_seconds?: number}} info
         */
        updateAutoStop(info) {
            if (!info) return;
            this.autoStop.enabled = info.enabled || false;
            this.autoStop.limitSeconds = info.limit_seconds || 0;
            this.autoStop.warningSeconds = info.warning_seconds || 0;
            this.autoStop.warningSent = info.warning_sent || false;
            this.autoStop.triggered = info.triggered || false;
            this.autoStop.maxRecordingSeconds = info.max_recording_seconds || 0;
            this.autoStop.remainingSeconds = info.remaining_seconds || 0;

            // Sync the client-side countdown reference point
            this._countdownServerRemaining = Math.max(0, info.remaining_seconds || 0);
            this._countdownLastUpdate = Date.now();
        },



        /**
         * Formats a total-seconds value into a short label like "3h 00m".
         * @param {number} totalSeconds
         * @returns {string}
         */
        formatLimit(totalSeconds) {
            if (totalSeconds <= 0) return '-';
            const h = Math.floor(totalSeconds / 3600);
            const m = Math.floor((totalSeconds % 3600) / 60);
            if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
            return `${m}m`;
        },

        /**
         * Cleans up timers when the component is destroyed.
         */
        cleanup() {
            if (this.recordingTimer.intervalId) {
                clearInterval(this.recordingTimer.intervalId);
                this.recordingTimer.intervalId = null;
            }
            console.log('🧹 Ingest store cleaned up');
        }
    });
});