/**
 * Connection Store - WebSocket Connection Management
 *
 * Centralized state for WebSocket connection, reconnection logic,
 * and connection status tracking with Alpine.js store pattern.
 */
document.addEventListener('alpine:init', () => {
    Alpine.store('connection', {
        // Connection State
        socket: null,
        status: 'connecting',           // 'connecting' | 'connected' | 'disconnected'
        text: 'Forbinder til server...',
        lastUpdate: 'Indlæser...',

        // Reconnection State
        reconnectAttempts: 0,
        maxReconnectAttempts: Infinity,  // Retry forever
        reconnectDelay: 1000,           // Base delay in ms
        reconnectTimeoutId: null,       // Track active reconnection timeout

        // Connection Actions
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

        setupSocketHandlers() {
            if (!this.socket) return;

            this.socket.onopen = () => {
                console.log('WebSocket connected');
                this.updateStatus('connected', 'Forbundet til server');
                this.reconnectAttempts = 0;
                this.cancelReconnect(); // Clear any pending reconnection
                this.onConnected();
            };

            this.socket.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    this.updateLastUpdate();
                    window.messageHandler?.handleMessage(message);

                } catch (error) {
                    console.error('Error parsing WebSocket message:', error);
                }
            };

            this.socket.onclose = () => {
                console.log('WebSocket disconnected');
                this.handleDisconnection();
            };

            this.socket.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.handleDisconnection();
            };
        },

        handleDisconnection() {
            this.updateStatus('disconnected', 'Forbindelse afbrudt');
            if (this.socket) {
                this.socket = null;
            }

            this.cancelReconnect();
            this.scheduleReconnect();
        },

        scheduleReconnect() {
            if (this.reconnectTimeoutId) return;

            this.reconnectAttempts++;
            const delay = Math.min(
                this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1),
                10000
            );

            this.updateStatus(
                'connecting',
                `Prøver at forbinde igen om ${Math.round(delay / 1000)}s... (forsøg #${this.reconnectAttempts})`
            );

            this.reconnectTimeoutId = setTimeout(() => {
                this.reconnectTimeoutId = null; // Clear the timeout ID
                this.connect();
            }, delay);
        },

        cancelReconnect() {
            if (this.reconnectTimeoutId) {
                clearTimeout(this.reconnectTimeoutId);
                this.reconnectTimeoutId = null;
            }
        },

        updateStatus(status, text) {
            this.status = status;
            this.text = text;
            console.log(`Connection status: ${status} - ${text}`);
        },

        updateLastUpdate() {
            const now = new Date().toLocaleTimeString('da-DK');
            this.lastUpdate = `Sidst opdateret: ${now}`;
        },

        onConnected() {
            console.log('WebSocket connected. Fetching initial state...');
            this.fetchInitialState();
        },

        async fetchInitialState() {
            try {
                const response = await fetch('/api/initial-state');
                if (!response.ok) {
                    throw new Error(`Failed to fetch initial state: ${response.status} ${response.statusText}`);
                }
                const initialStateData = await response.json();

                // Pass the initial state to the message handler as if it came from the WebSocket
                // This reuses the existing data handling logic
                window.messageHandler?.handleMessage({
                    type: 'initial_state',
                    data: initialStateData
                });

                console.log('Successfully fetched and processed initial state.');

            } catch (error) {
                console.error('Error fetching initial state:', error);
                this.updateStatus('disconnected', 'Kunne ikke hente start-data');
            }
        },

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