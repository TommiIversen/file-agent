// @ts-check

/** @type {any} */
var Alpine;

/**
 * @file Events Viewer Store
 * Manages system events viewing and filtering functionality for the Alpine.js UI.
 * @author Tommi Iversen 
 */

/**
 * Represents a log event.
 * @typedef {Object} LogEvent
 * @property {string} timestamp - The ISO 8601 timestamp of when the event occurred.
 * @property {string} level - The severity level of the event (e.g., 'info', 'warning', 'error').
 * @property {string} event_type - The type of the event (e.g., 'FileDetected', 'NetworkDown').
 * @property {Object.<string, any>|null} details - A key-value map of additional event details, or null.
 */

/**
 * Represents statistics about the logged events.
 * @typedef {Object} EventStats
 * @property {number} total_events - The total number of events currently in the log.
 * @property {number} max_capacity - The maximum number of events the log can hold.
 * @property {Object.<string, number>} levels - A map of event levels to their counts.
 * @property {Object.<string, number>} event_types - A map of event types to their counts.
 * @property {string|null} oldest_event - The ISO 8601 timestamp of the oldest event.
 * @property {string|null} newest_event - The ISO 8601 timestamp of the newest event.
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('eventsViewer', {
        // === STATE PROPERTIES ===

        /**
         * Whether the events viewer modal is open.
         * @type {boolean}
         */
        isOpen: false,

        /**
         * True when events are being loaded from the API.
         * @type {boolean}
         */
        isLoading: false,

        /**
         * Holds any error message that occurred during an API call.
         * @type {string|null}
         */
        error: null,
        
        /**
         * The master list of all events loaded from the API.
         * @type {LogEvent[]}
         */
        events: [],

        /**
         * The list of events after all filters have been applied.
         * @type {LogEvent[]}
         */
        filteredEvents: [],
        
        /**
         * The current filter for event severity level.
         * @type {'all'|'info'|'warning'|'error'}
         */
        levelFilter: 'all',

        /**
         * The current filter for event type. 'all' means no filter.
         * @type {string}
         */
        eventTypeFilter: 'all',

        /**
         * A sorted list of unique event types available for filtering.
         * @type {string[]}
         */
        availableEventTypes: [],
        
        /**
         * The current page number for pagination.
         * @type {number}
         */
        currentPage: 1,

        /**
         * The number of events to display per page.
         * @type {number}
         */
        eventsPerPage: 50,

        /**
         * The total number of events after filtering.
         * @type {number}
         */
        totalEvents: 0,
        
        /**
         * Statistics about the events in the log.
         * @type {EventStats}
         */
        stats: {
            total_events: 0,
            max_capacity: 200,
            levels: {},
            event_types: {},
            oldest_event: null,
            newest_event: null
        },
        
        // Auto-refresh functionality is not implemented yet.
        autoRefresh: false,
        refreshInterval: null,
        
        // === METHODS ===

        /**
         * Opens the events viewer modal and loads initial data.
         */
        openModal() {
            this.isOpen = true;
            this.loadEvents();
            this.loadStats();
        },
        
        /**
         * Closes the events viewer modal.
         */
        closeModal() {
            this.isOpen = false;
        },
        
        /**
         * Fetches the list of events from the API based on the current level filter.
         * @async
         */
        async loadEvents() {
            this.isLoading = true;
            this.error = null;
            
            try {
                const params = new URLSearchParams();
                if (this.levelFilter !== 'all') {
                    params.append('level', this.levelFilter);
                }
                
                const response = await fetch(`/api/events/?${params.toString()}`);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                this.events = await response.json();
                this.updateAvailableEventTypes();
                this.applyFilters();
                
            } catch (error) {
                console.error('Failed to load events:', error);
                if (error instanceof Error) {
                    this.error = `Failed to load events: ${error.message}`;
                } else {
                    this.error = 'Failed to load events: An unknown error occurred';
                }
            } finally {
                this.isLoading = false;
            }
        },
        
        /**
         * Fetches event statistics from the API.
         * @async
         */
        async loadStats() {
            try {
                const response = await fetch('/api/events/stats');
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                this.stats = await response.json();
                
            } catch (error) {
                console.error('Failed to load event stats:', error);
                // Optionally set an error state for stats loading as well
            }
        },
        
        /**
         * Populates `availableEventTypes` from the master list of events.
         */
        updateAvailableEventTypes() {
            const types = [...new Set(this.events.map((/** @type {LogEvent} */ event) => event.event_type))];
            this.availableEventTypes = types.sort();
        },
        
        /**
         * Applies the current filters to the master `events` list and updates `filteredEvents`.
         */
        applyFilters() {
            let filtered = [...this.events];
            
            // Filter by event type
            if (this.eventTypeFilter !== 'all') {
                filtered = filtered.filter(event => event.event_type === this.eventTypeFilter);
            }
            
            this.filteredEvents = filtered;
            this.totalEvents = filtered.length;
        },
        
        /**
         * Sets the level filter and reloads the events from the API.
         * @param {'all'|'info'|'warning'|'error'} level - The level to filter by.
         */
        setLevelFilter(level) {
            this.levelFilter = level;
            this.currentPage = 1;
            this.loadEvents();
        },
        
        /**
         * Sets the event type filter and reapplies filters to the existing event list.
         * @param {string} eventType - The event type to filter by.
         */
        setEventTypeFilter(eventType) {
            this.eventTypeFilter = eventType;
            this.currentPage = 1;
            this.applyFilters();
        },
        
        // === GETTERS ===

        /**
         * Gets the slice of events for the current page.
         * @returns {LogEvent[]} A subset of the filtered events for the current page.
         */
        get paginatedEvents() {
            const start = (this.currentPage - 1) * this.eventsPerPage;
            const end = start + this.eventsPerPage;
            return this.filteredEvents.slice(start, end);
        },
        
        /**
         * Calculates the total number of pages for pagination.
         * @returns {number} The total number of pages.
         */
        get totalPages() {
            return Math.ceil(this.totalEvents / this.eventsPerPage);
        },
        
        // === PAGINATION METHODS ===

        /**
         * Navigates to a specific page number.
         * @param {number} page - The page number to navigate to.
         */
        goToPage(page) {
            if (page >= 1 && page <= this.totalPages) {
                this.currentPage = page;
            }
        },
        
        /**
         * Navigates to the next page.
         */
        nextPage() {
            this.goToPage(this.currentPage + 1);
        },
        
        /**
         * Navigates to the previous page.
         */
        previousPage() {
            this.goToPage(this.currentPage - 1);
        },
        
        // === UI HELPERS ===

        /**
         * Manually triggers a refresh of both events and stats.
         */
        refresh() {
            this.loadEvents();
            this.loadStats();
        },
        
        /**
         * Gets the Tailwind CSS classes for a level's badge color.
         * @param {string} level - The event level.
         * @returns {string} The corresponding CSS classes.
         */
        getLevelBadgeColor(level) {
            switch (level.toLowerCase()) {
                case 'error':
                    return 'bg-red-500 text-white';
                case 'warning':
                    return 'bg-yellow-500 text-black';
                case 'info':
                    return 'bg-blue-500 text-white';
                default:
                    return 'bg-gray-500 text-white';
            }
        },
        
        /**
         * Gets an icon for a given event type.
         * @param {string} eventType - The event type.
         * @returns {string} An emoji icon.
         */
        getEventTypeIcon(eventType) {
            if (eventType.includes('Network')) return '🌐';
            if (eventType.includes('Storage')) return '💾';
            if (eventType.includes('Mount')) return '🔗';
            if (eventType.includes('File')) return '📄';
            if (eventType.includes('Scanner')) return '🔍';
            if (eventType.includes('Destination')) return '🎯';
            return '📊';
        },
        
        /**
         * Formats a timestamp for display in the UI.
         * @param {string} timestamp - The ISO 8601 timestamp.
         * @returns {string} A localized, human-readable date and time string.
         */
        formatTimestamp(timestamp) {
            const date = new Date(timestamp);
            return date.toLocaleString('da-DK', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        },
        
        /**
         * Formats a timestamp into a relative time string (e.g., "2 minutes ago").
         * @param {string} timestamp - The ISO 8601 timestamp.
         * @returns {string} A relative time string.
         */
        formatRelativeTime(timestamp) {
            const now = new Date();
            const eventTime = new Date(timestamp);
            const diffInSeconds = Math.floor((now.getTime() - eventTime.getTime()) / 1000);
            
            if (diffInSeconds < 60) {
                return `${diffInSeconds} sek siden`;
            } else if (diffInSeconds < 3600) {
                const minutes = Math.floor(diffInSeconds / 60);
                return `${minutes} min siden`;
            } else if (diffInSeconds < 86400) {
                const hours = Math.floor(diffInSeconds / 3600);
                return `${hours} timer siden`;
            } else {
                const days = Math.floor(diffInSeconds / 86400);
                return `${days} dage siden`;
            }
        },
        
        /**
         * Triggers a download of the currently loaded events as a CSV file.
         */
        downloadEvents() {
            try {
                const events = this.events;
                if (!events.length) {
                    console.warn('No events to download');
                    return;
                }

                // Create CSV content
                const headers = ['Timestamp', 'Level', 'Event Type', 'Details'];
                const csvContent = [
                    headers.join(','),
                    ...events.map((/** @type {LogEvent} */ event) => {
                        const timestamp = this.formatTimestamp(event.timestamp);
                        const level = event.level;
                        const eventType = event.event_type;
                        const details = event.details 
                            ? Object.entries(event.details).map(([k,v]) => `${k}: ${v}`).join(' | ')
                            : 'No details';
                        
                        // Escape CSV values
                        return [timestamp, level, eventType, details]
                            .map(field => `"${String(field).replace(/"/g, '""')}"`)
                            .join(',');
                    })
                ].join('\n');

                // Create and download file
                const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
                const link = document.createElement('a');
                
                if (link.download !== undefined) {
                    const url = URL.createObjectURL(blob);
                    link.setAttribute('href', url);
                    link.setAttribute('download', `events-${new Date().toISOString().slice(0,19).replace(/:/g,'-')}.csv`);
                    link.style.visibility = 'hidden';
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    URL.revokeObjectURL(url);
                }
            } catch (error) {
                console.error('Error downloading events:', error);
            }
        },
        
        /**
         * Formats an event's details object into a single string for display.
         * @param {Object.<string, any>|null} details - The details object.
         * @returns {string|null} A formatted string or null if details are empty.
         */
        getFormattedDetails(details) {
            if (!details || Object.keys(details).length === 0) {
                return null;
            }
            
            return Object.entries(details)
                .map(([key, value]) => `${key}: ${value}`)
                .join(', ');
        }
    });
});