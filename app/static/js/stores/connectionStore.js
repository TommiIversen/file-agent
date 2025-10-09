/**
 * Connection Store - WebSocket Connection Management
 * 
 * Centralized state for WebSocket connection, reconnection logic,
 * and connection status tracking with Alpine.js store pattern.
 */

// Connection Store with Alpine.js
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
        isReconnecting: false,
        
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
                this.isReconnecting = false;
                
                // Notify other stores/services
                this.onConnected();
            };
            
            this.socket.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    this.updateLastUpdate();
                    
                    // Dispatch message to message handler
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
            
            if (this.isReconnecting) return; // Prevent multiple reconnection attempts
            
            this.isReconnecting = true;
            this.reconnectAttempts++;
            
            // Calculate delay with exponential backoff, capped at 10 seconds
            const delay = Math.min(
                this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1), 
                10000
            );
            
            this.updateStatus(
                'connecting', 
                `Prøver at forbinde igen om ${Math.round(delay/1000)}s... (forsøg #${this.reconnectAttempts})`
            );
            
            setTimeout(() => {
                this.connect();
            }, delay);
        },
        
        disconnect() {
            if (this.socket) {
                this.socket.close();
                this.socket = null;
            }
            this.updateStatus('disconnected', 'Forbindelse lukket');
        },
        
        // Status Management
        updateStatus(status, text) {
            this.status = status;
            this.text = text;
            console.log(`Connection status: ${status} - ${text}`);
        },
        
        updateLastUpdate() {
            const now = new Date().toLocaleTimeString('da-DK');
            this.lastUpdate = `Sidst opdateret: ${now}`;
        },
        
        // Connection Events
        onConnected() {
            // Load initial data when connected
            Alpine.store('storage')?.loadStorageData();
        },
        
        // Computed Properties
        get isConnected() {
            return this.status === 'connected';
        },
        
        get isConnecting() {
            return this.status === 'connecting';
        },
        
        get isDisconnected() {
            return this.status === 'disconnected';
        },
        
        get statusColor() {
            switch (this.status) {
                case 'connected': return 'bg-green-500';
                case 'connecting': return 'bg-yellow-500';
                case 'disconnected': return 'bg-red-500';
                default: return 'bg-gray-500';
            }
        }
    });
});