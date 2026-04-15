// @ts-check

/**
 * @file Audio Store - Alpine.js store for audio recording status
 *
 * Manages audio recording state and provides reactive state
 * for UI components that display recording indicators.
 */

document.addEventListener('alpine:init', () => {
    /** @type {AudioStore} */
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
                }
            } catch (e) {
                // Audio domain may not be configured — that's OK
            }
        },

        /**
         * Handle audio recording started event
         * @param {object} data
         */
        handleStarted(data) {
            this.enabled = true;
            this.recording = true;
            this.sessionId = data.session_id;
            this.trackCount = data.track_count || data.tracks?.length || 0;
            this.samplerate = data.samplerate || 0;
            this.tracks = data.tracks || [];
            this.startedAt = data.timestamp;
            this.overflowCount = 0;
            this.lastError = null;
            this.deviceDisconnected = false;
        },

        /**
         * Handle audio recording stopped event
         * @param {object} data
         */
        handleStopped(data) {
            this.recording = false;
            this.overflowCount = data.overflow_count || 0;
            this.sessionId = null;
            this.startedAt = null;
            this.tracks = [];
            this.trackCount = 0;
            this.samplerate = 0;
        },

        /**
         * Handle audio recording error event
         * @param {object} data
         */
        handleError(data) {
            this.lastError = data.error;
            if (!data.recoverable) {
                this.recording = false;
            }
        },

        /**
         * Handle audio device disconnected event
         * @param {object} data
         */
        handleDeviceDisconnected(data) {
            this.deviceDisconnected = true;
            this.recording = false;
        },

        /**
         * Handle audio overflow warning event
         * @param {object} data
         */
        handleOverflowWarning(data) {
            this.overflowCount = data.total_drops || 0;
        },
    };

    Alpine.store('audio', audioStore);
});
