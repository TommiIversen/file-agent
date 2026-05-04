// @ts-check

/**
 * @typedef {{label: string, peaks: number[], clip: boolean}} LevelTrack
 * @typedef {{label: string, channels: number[], mode: string}} TrackConfig
 * @typedef {{session_id?: string, track_count?: number, tracks?: string[], samplerate?: number, timestamp?: string}} AudioStartedData
 * @typedef {{overflow_count?: number}} AudioStoppedData
 * @typedef {{error?: string, recoverable?: boolean}} AudioErrorData
 * @typedef {{total_drops?: number}} AudioOverflowData
 * @typedef {{tracks?: LevelTrack[]}} AudioLevelsData
 */

/** @type {any} */
const _vuWin = window;

/**
 * @file Audio Store - Alpine.js store for audio recording status
 *
 * Manages audio recording state and provides reactive state
 * for UI components that display recording indicators.
 */

document.addEventListener('alpine:init', () => {
    const audioStore = {
        // === STATE ===

        /** @type {boolean} */
        enabled: false,

        /** @type {boolean} */
        recording: false,

        /** @type {string|null} */
        sessionId: null,

        /** @type {number} */
        trackCount: 0,

        /** @type {number} */
        samplerate: 0,

        /** @type {string[]} */
        tracks: [],

        /** @type {string|null} */
        startedAt: null,

        /** @type {number} */
        overflowCount: 0,

        /** @type {string|null} */
        lastError: null,

        /** @type {boolean} */
        deviceDisconnected: false,

        /** @type {Array<{label: string, peaks: number[], clip: boolean}>} */
        levelTracks: [],

        // === METHODS ===

        async init() {
            try {
                const resp = await fetch('/api/audio/status');
                if (resp.ok) {
                    const data = await resp.json();
                    this.enabled = data.enabled || false;
                    this.recording = data.recording || false;
                    this.sessionId = data.session_id || null;
                    this.trackCount = data.track_count || 0;
                    this.samplerate = data.samplerate || 0;
                    this.overflowCount = data.overflow_count || 0;
                    this._initLevelTracks(data.tracks_config || []);
                }
            } catch (e) {
                // Audio domain may not be configured — that's OK
            }
        },

        /**
         * Handle audio recording started event
         * @param {AudioStartedData} data
         */
        handleStarted(data) {
            this.enabled = true;
            this.recording = true;
            this.sessionId = data.session_id ?? null;
            this.trackCount = data.track_count || data.tracks?.length || 0;
            this.samplerate = data.samplerate || 0;
            this.tracks = data.tracks || [];
            this.startedAt = data.timestamp ?? null;
            this.overflowCount = 0;
            this.lastError = null;
            this.deviceDisconnected = false;
        },

        /**
         * Handle audio recording stopped event
         * @param {AudioStoppedData} data
         */
        handleStopped(data) {
            this.recording = false;
            this.overflowCount = data.overflow_count || 0;
            this.sessionId = null;
            this.startedAt = null;
            this.tracks = [];
            this.trackCount = 0;
            this.samplerate = 0;
            this.clearLevels();
        },

        /**
         * Handle audio recording error event
         * @param {AudioErrorData} data
         */
        handleError(data) {
            this.lastError = data.error ?? null;
            if (!data.recoverable) {
                this.recording = false;
            }
        },

        /**
         * Handle audio device disconnected event
         * @param {object} _data
         */
        handleDeviceDisconnected(_data) {
            this.deviceDisconnected = true;
            this.recording = false;
        },

        /**
         * Handle audio overflow warning event
         * @param {AudioOverflowData} data
         */
        handleOverflowWarning(data) {
            this.overflowCount = data.total_drops || 0;
        },

        /**
         * Handle audio levels update from WebSocket
         * @param {AudioLevelsData} data
         */
        updateLevels(data) {
            /** @type {LevelTrack[]} */
            const tracks = data.tracks || [];

            // Update Alpine store ONLY when track structure changes (rare).
            // This keeps x-show="levelTracks.length > 0" working without
            // per-frame reactivity cost from peak value changes.
            const structureChanged =
                this.levelTracks.length !== tracks.length ||
                tracks.some((t, i) => t.label !== this.levelTracks[i]?.label);

            if (structureChanged) {
                this.levelTracks = tracks.map(t => ({
                    label: t.label,
                    peaks: t.peaks.map(() => 0),
                    clip: false,
                }));
            }

            // Route peak data directly to canvas renderer (bypasses Alpine)
            if (_vuWin.updateVuMeter) {
                _vuWin.updateVuMeter(tracks);
            }
        },

        /**
         * Zero out level meters but keep track structure.
         */
        clearLevels() {
            this.levelTracks = this.levelTracks.map(t => ({
                label: t.label,
                peaks: t.peaks.map(() => 0),
                clip: false,
            }));
            if (_vuWin.clearVuMeter) {
                _vuWin.clearVuMeter();
            }
        },

        /**
         * Build idle levelTracks from track config (labels + channel count).
         * @param {TrackConfig[]} config
         */
        _initLevelTracks(config) {
            if (this.levelTracks.length > 0) return;
            this.levelTracks = config.map(t => ({
                label: t.label,
                peaks: (t.channels || []).map(() => 0),
                clip: false,
            }));

            // Send idle track structure to canvas so meters render in standby
            if (_vuWin.updateVuMeter) {
                _vuWin.updateVuMeter(this.levelTracks);
            }
        },
    };

    Alpine.store('audio', audioStore);
});
