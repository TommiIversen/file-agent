// @ts-check

/**
 * @file Connection Store - WebSocket Connection Management
 *
 * Centralized state for WebSocket connection, reconnection logic,
 * and connection status tracking with Alpine.js store pattern.
 */



document.addEventListener('alpine:init', () => {
    Alpine.store('connection', {
        // === STATE PROPERTIES ===

        /**
         * The WebSocket instance.
         * @type {WebSocket|null}
         */
        socket: null,

        /**
         * The current status of the connection.
         * @type {ConnectionStatus}
         */
        status: 'connecting',

        /**
         * A user-friendly text description of the current status.
         * @type {string}
         */
        text: 'Forbinder til server...',

        /**
         * Timestamp of the last received message.
         * @type {string}
         */
        lastUpdate: 'Indlæser...',

        /**
         * The number of consecutive reconnection attempts.
         * @type {number}
         */
        reconnectAttempts: 0,

        /**
         * The maximum number of times to try reconnecting.
         * @type {number}
         */
        maxReconnectAttempts: Infinity,

        /**
         * The base delay for reconnection logic, in milliseconds.
         * @type {number}
         */
        reconnectDelay: 1000,

        /**
         * The ID of the scheduled reconnection timeout, used for cancellation.
         * @type {number|null}
         */
        reconnectTimeoutId: null,

        // === METHODS ===

        /**
         * Initializes the dashboard by fetching the initial state and then connecting the WebSocket.
         * @returns {Promise<void>}
         */
        async initDashboard() {
            try {
                // 1. Fetch initial data FIRST
                console.log('Fetching initial state...');
                await this.fetchInitialState();

                // 2. Once data is fetched, connect for real-time updates
                console.log('Initial state loaded. Connecting to WebSocket...');
                this.connect();

            } catch (error) {
                console.error('Failed to initialize dashboard:', error);
                this.updateStatus('disconnected', 'Kunne ikke hente start-data');
            }
        },

        /**
         * Establishes the WebSocket connection.
         */
        connect() {
            try {
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const wsUrl = `${protocol}//${window.location.host}/api/ws/live`;

                console.log(`Connecting to WebSocket: ${wsUrl}`);
                this.socket = new WebSocket(wsUrl);
                this.setupSocketHandlers();

            } catch (error) {
                console.error('WebSocket connection error:', error);
                this.handleDisconnection();
            }
        },

        /**
         * Sets up the event handlers for the WebSocket instance.
         */
        setupSocketHandlers() {
            if (!this.socket) return;

            this.socket.onopen = () => {
                console.log('WebSocket connected');
                this.updateStatus('connected', 'Forbundet til server');
                this.reconnectAttempts = 0;
                this.cancelReconnect();
                this.onConnected();
            };

            this.socket.onmessage = (/** @type {MessageEvent} */ event) => {
                try {
                    const message = JSON.parse(event.data);
                    this.updateLastUpdate();
                    if (window.messageHandler) {
                        window.messageHandler.handleMessage(message);
                    }
                } catch (error) {
                    console.error('Error parsing WebSocket message:', error);
                }
            };

            this.socket.onclose = () => {
                console.log('WebSocket disconnected');
                this.handleDisconnection();
            };

            this.socket.onerror = (/** @type {Event} */ event) => {
                console.error('WebSocket error:', event);
                this.handleDisconnection();
            };
        },

        /**
         * Handles the logic for when a connection is closed or fails.
         */
        handleDisconnection() {
            this.updateStatus('disconnected', 'Forbindelse afbrudt');
            if (this.socket) {
                this.socket = null;
            }

            this.cancelReconnect();
            this.scheduleReconnect();
        },

        /**
         * Schedules a reconnection attempt with an exponential backoff delay.
         */
        scheduleReconnect() {
            if (this.reconnectTimeoutId) return;
            if (this.reconnectAttempts >= this.maxReconnectAttempts) return;

            this.reconnectAttempts++;
            const delay = Math.min(
                this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1),
                10000 // Max delay of 10 seconds
            );

            this.updateStatus(
                'connecting',
                `Prøver at forbinde igen om ${Math.round(delay / 1000)}s... (forsøg #${this.reconnectAttempts})`
            );

            this.reconnectTimeoutId = window.setTimeout(() => {
                this.reconnectTimeoutId = null;
                this.connect();
            }, delay);
        },

        /**
         * Cancels any pending reconnection attempt.
         */
        cancelReconnect() {
            if (this.reconnectTimeoutId) {
                clearTimeout(this.reconnectTimeoutId);
                this.reconnectTimeoutId = null;
            }
        },

        /**
         * Updates the connection status and display text.
         * @param {ConnectionStatus} status - The new connection status.
         * @param {string} text - The user-facing text to display.
         */
        updateStatus(status, text) {
            this.status = status;
            this.text = text;
            console.log(`Connection status: ${status} - ${text}`);
        },

        /**
         * Updates the 'last updated' timestamp.
         */
        updateLastUpdate() {
            const now = new Date().toLocaleTimeString('da-DK');
            this.lastUpdate = `Sidst opdateret: ${now}`;
        },

        /**
         * Callback for when the WebSocket connection is successfully established.
         * Fetches the initial state again to ensure data is fresh.
         */
        onConnected() {
            console.log('WebSocket connected. Fetching initial state...');
            this.fetchInitialState();
        },

        /**
         * Fetches the complete initial state from the backend.
         * @returns {Promise<void>}
         * @throws {Error} If the network request fails.
         */
        async fetchInitialState() {
            try {
                const response = await fetch('/api/initial-state');
                if (!response.ok) {
                    throw new Error(`Failed to fetch initial state: ${response.status} ${response.statusText}`);
                }
                const initialStateData = await response.json();

                if (window.messageHandler) {
                    window.messageHandler.handleMessage({
                        type: 'initial_state',
                        data: initialStateData
                    });
                }

                console.log('Successfully fetched and processed initial state.');

            } catch (error) {
                console.error('Error fetching initial state:', error);
                // Re-throw the error so the caller (initDashboard) can handle it.
                throw error;
            }
        },

        // === GETTERS ===

        /**
         * Gets the Tailwind CSS background color class for the current status.
         * @returns {string} The CSS class.
         */
        get statusColor() {
            switch (this.status) {
                case 'connected':
                    return 'bg-green-500';
                case 'connecting':
                    return 'bg-yellow-500';
                case 'disconnected':
                    return 'bg-red-500';
                default:
                    return 'bg-gray-500';
            }
        }
    });
});