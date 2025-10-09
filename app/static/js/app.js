/**
 * File Transfer Agent - Main Application Initialization
 * 
 * Main entry point for the File Transfer Agent frontend application.
 * Initializes Alpine.js stores, services, and starts the application.
 */

// Application Configuration
const APP_CONFIG = {
    name: 'File Transfer Agent',
    version: '1.0.0',
    debug: true, // Set to false in production
    
    // WebSocket Configuration
    websocket: {
        autoConnect: true,
        reconnectOnError: true,
        heartbeatInterval: 30000, // 30 seconds
    },
    
    // UI Configuration
    ui: {
        defaultSortBy: 'discovered',
        refreshInterval: 5000, // 5 seconds
        animationDuration: 300,
    }
};

/**
 * Main Application Class
 */
class FileTransferApp {
    constructor() {
        this.initialized = false;
        this.stores = {};
        this.services = {};
        
        // Bind methods
        this.init = this.init.bind(this);
        this.onDocumentReady = this.onDocumentReady.bind(this);
        this.onAlpineInit = this.onAlpineInit.bind(this);
    }
    
    /**
     * Initialize the application
     */
    async init() {
        if (this.initialized) {
            console.warn('Application already initialized');
            return;
        }
        
        console.log(`🚀 Initializing ${APP_CONFIG.name} v${APP_CONFIG.version}`);
        
        try {
            // Setup event listeners
            this.setupEventListeners();
            
            // Wait for DOM to be ready
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', this.onDocumentReady);
            } else {
                await this.onDocumentReady();
            }
            
        } catch (error) {
            console.error('Failed to initialize application:', error);
            this.handleInitializationError(error);
        }
    }
    
    /**
     * Document ready handler
     */
    async onDocumentReady() {
        console.log('📄 Document ready, setting up Alpine.js...');
        
        // Setup Alpine.js
        this.setupAlpine();
    }
    
    /**
     * Setup Alpine.js initialization
     */
    setupAlpine() {
        // Set up Alpine.js event listeners
        document.addEventListener('alpine:init', this.onAlpineInit);
        
        // Configure Alpine.js
        if (window.Alpine) {
            // Alpine is already loaded, initialize immediately
            this.onAlpineInit();
        }
    }
    
    /**
     * Alpine.js initialization handler
     */
    onAlpineInit() {
        console.log('🔧 Alpine.js initializing...');
        
        // Wait a bit for stores to be fully initialized
        setTimeout(() => {
            this.initializeStores();
            this.initializeServices();
            this.startApplication();
        }, 100);
    }
    
    /**
     * Initialize Alpine.js stores
     */
    initializeStores() {
        console.log('🏪 Initializing stores...');
        
        // Get store references
        this.stores = {
            connection: Alpine.store('connection'),
            files: Alpine.store('files'),
            storage: Alpine.store('storage')
        };
        
        // Validate stores
        const missingStores = Object.entries(this.stores)
            .filter(([name, store]) => !store)
            .map(([name]) => name);
            
        if (missingStores.length > 0) {
            console.error('Missing stores:', missingStores);
            throw new Error(`Missing required stores: ${missingStores.join(', ')}`);
        }
        
        console.log('✅ All stores initialized successfully');
    }
    
    /**
     * Initialize services
     */
    initializeServices() {
        console.log('🔧 Initializing services...');
        
        // Initialize services
        this.services = {
            messageHandler: window.messageHandler,
            uiHelpers: window.UIHelpers
        };
        
        // Validate services
        const missingServices = Object.entries(this.services)
            .filter(([name, service]) => !service)
            .map(([name]) => name);
            
        if (missingServices.length > 0) {
            console.error('Missing services:', missingServices);
            throw new Error(`Missing required services: ${missingServices.join(', ')}`);
        }
        
        console.log('✅ All services initialized successfully');
    }
    
    /**
     * Start the main application
     */
    startApplication() {
        console.log('🚀 Starting application...');
        
        // Start WebSocket connection if auto-connect is enabled
        if (APP_CONFIG.websocket.autoConnect) {
            this.startWebSocketConnection();
        }
        
        // Setup periodic tasks
        this.setupPeriodicTasks();
        
        // Mark as initialized
        this.initialized = true;
        
        console.log('✅ Application started successfully');
        
        // Dispatch application ready event
        this.dispatchAppEvent('app:ready', {
            config: APP_CONFIG,
            stores: Object.keys(this.stores),
            services: Object.keys(this.services)
        });
    }
    
    /**
     * Start WebSocket connection
     */
    startWebSocketConnection() {
        console.log('🔌 Starting WebSocket connection...');
        
        if (this.stores.connection) {
            this.stores.connection.connect();
        } else {
            console.error('Connection store not available');
        }
    }
    
    /**
     * Setup periodic tasks
     */
    setupPeriodicTasks() {
        // Setup heartbeat if configured
        if (APP_CONFIG.websocket.heartbeatInterval > 0) {
            setInterval(() => {
                this.heartbeat();
            }, APP_CONFIG.websocket.heartbeatInterval);
        }
    }
    
    /**
     * Application heartbeat
     */
    heartbeat() {
        if (APP_CONFIG.debug) {
            console.log('💓 Application heartbeat');
        }
        
        // Check store health
        const storeHealth = this.getStoreHealth();
        
        // Dispatch heartbeat event
        this.dispatchAppEvent('app:heartbeat', {
            timestamp: new Date().toISOString(),
            storeHealth,
            connectionStatus: this.stores.connection?.status
        });
    }
    
    /**
     * Get store health status
     */
    getStoreHealth() {
        return {
            connection: !!this.stores.connection,
            files: !!this.stores.files,
            storage: !!this.stores.storage,
            filesCount: this.stores.files?.statistics?.totalFiles || 0,
            connectionStatus: this.stores.connection?.status || 'unknown'
        };
    }
    
    /**
     * Setup event listeners
     */
    setupEventListeners() {
        // Global error handler
        window.addEventListener('error', (event) => {
            console.error('Global error:', event.error);
            this.handleGlobalError(event.error);
        });
        
        // Unhandled promise rejection handler
        window.addEventListener('unhandledrejection', (event) => {
            console.error('Unhandled promise rejection:', event.reason);
            this.handleGlobalError(event.reason);
        });
        
        // Page visibility change handler
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                console.log('📴 Page hidden');
                this.dispatchAppEvent('app:hidden');
            } else {
                console.log('👁️ Page visible');
                this.dispatchAppEvent('app:visible');
            }
        });
    }
    
    /**
     * Handle initialization errors
     */
    handleInitializationError(error) {
        console.error('❌ Application initialization failed:', error);
        
        // Try to show user-friendly error message
        const errorContainer = document.getElementById('error-container');
        if (errorContainer) {
            errorContainer.innerHTML = `
                <div class="bg-red-900 bg-opacity-50 rounded-lg p-4 border border-red-600">
                    <h3 class="text-red-200 font-bold mb-2">Application Failed to Start</h3>
                    <p class="text-red-300 text-sm">
                        ${error.message || 'Unknown error occurred during initialization'}
                    </p>
                    <button class="mt-3 bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded text-sm"
                            onclick="location.reload()">
                        Reload Page
                    </button>
                </div>
            `;
            errorContainer.style.display = 'block';
        }
    }
    
    /**
     * Handle global errors
     */
    handleGlobalError(error) {
        // Log error details
        console.error('Global error details:', {
            message: error.message,
            stack: error.stack,
            timestamp: new Date().toISOString()
        });
        
        // Dispatch error event
        this.dispatchAppEvent('app:error', {
            error: error.message,
            timestamp: new Date().toISOString()
        });
    }
    
    /**
     * Dispatch custom application events
     */
    dispatchAppEvent(eventName, detail = {}) {
        const event = new CustomEvent(eventName, {
            detail: {
                app: this,
                config: APP_CONFIG,
                ...detail
            }
        });
        
        document.dispatchEvent(event);
        
        if (APP_CONFIG.debug) {
            console.log(`📡 Event dispatched: ${eventName}`, detail);
        }
    }
    
    /**
     * Get application status
     */
    getStatus() {
        return {
            initialized: this.initialized,
            config: APP_CONFIG,
            stores: this.getStoreHealth(),
            services: Object.keys(this.services),
            timestamp: new Date().toISOString()
        };
    }
}

// Create and initialize the application
const app = new FileTransferApp();

// Make app available globally for debugging
window.fileTransferApp = app;

// Auto-initialize when script loads
app.init().catch(error => {
    console.error('Failed to start File Transfer Agent:', error);
});

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = FileTransferApp;
}