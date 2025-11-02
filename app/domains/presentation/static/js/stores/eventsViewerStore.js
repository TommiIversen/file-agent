/**
 * Events Viewer Store
 * Manages system events viewing and filtering functionality
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('eventsViewer', {
        // Modal state
        isOpen: false,
        isLoading: false,
        error: null,
        
        // Events data
        events: [],
        filteredEvents: [],
        
        // Filters
        levelFilter: 'all', // 'all', 'info', 'warning', 'error'
        eventTypeFilter: 'all', // 'all' or specific event type
        availableEventTypes: [],
        
        // Pagination
        currentPage: 1,
        eventsPerPage: 50,
        totalEvents: 0,
        
        // Stats
        stats: {
            total_events: 0,
            max_capacity: 200,
            levels: {},
            event_types: {},
            oldest_event: null,
            newest_event: null
        },
        
        // Auto-refresh
        autoRefresh: false,
        refreshInterval: null,
        
        /**
         * Open the events viewer modal
         */
        openModal() {
            this.isOpen = true;
            this.loadEvents();
            this.loadStats();
        },
        
        /**
         * Close the events viewer modal
         */
        closeModal() {
            this.isOpen = false;
        },
        
        /**
         * Load events from API
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
                this.error = `Failed to load events: ${error.message}`;
            } finally {
                this.isLoading = false;
            }
        },
        
        /**
         * Load event statistics
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
            }
        },
        
        /**
         * Update available event types for filtering
         */
        updateAvailableEventTypes() {
            const types = [...new Set(this.events.map(event => event.event_type))];
            this.availableEventTypes = types.sort();
        },
        
        /**
         * Apply current filters to events
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
         * Set level filter
         */
        setLevelFilter(level) {
            this.levelFilter = level;
            this.currentPage = 1;
            this.loadEvents();
        },
        
        /**
         * Set event type filter
         */
        setEventTypeFilter(eventType) {
            this.eventTypeFilter = eventType;
            this.currentPage = 1;
            this.applyFilters();
        },
        
        /**
         * Get events for current page
         */
        get paginatedEvents() {
            const start = (this.currentPage - 1) * this.eventsPerPage;
            const end = start + this.eventsPerPage;
            return this.filteredEvents.slice(start, end);
        },
        
        /**
         * Get total number of pages
         */
        get totalPages() {
            return Math.ceil(this.totalEvents / this.eventsPerPage);
        },
        
        /**
         * Navigate to specific page
         */
        goToPage(page) {
            if (page >= 1 && page <= this.totalPages) {
                this.currentPage = page;
            }
        },
        
        /**
         * Go to next page
         */
        nextPage() {
            this.goToPage(this.currentPage + 1);
        },
        
        /**
         * Go to previous page
         */
        previousPage() {
            this.goToPage(this.currentPage - 1);
        },
        
        /**
         * Manually refresh events
         */
        refresh() {
            this.loadEvents();
            this.loadStats();
        },
        
        /**
         * Get level badge color
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
         * Get event type icon
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
         * Format timestamp for display
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
         * Format relative time (e.g., "2 minutes ago")
         */
        formatRelativeTime(timestamp) {
            const now = new Date();
            const eventTime = new Date(timestamp);
            const diffInSeconds = Math.floor((now - eventTime) / 1000);
            
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
         * Download events as CSV
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
                    ...events.map(event => {
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
         * Get formatted details for display
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