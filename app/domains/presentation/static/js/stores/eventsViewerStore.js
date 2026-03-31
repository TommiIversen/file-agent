// @ts-check



document.addEventListener('alpine:init', () => {
    Alpine.store('eventsViewer', {
        // === STATE ===
        isOpen: false,
        isLoading: false,
        isLoadingMore: false,
        error: null,
        hasMore: true,

        /** @type {LogEvent[]} All loaded events (newest first) */
        events: [],
        /** @type {LogEvent[]} Events after client-side type filter */
        filteredEvents: [],

        levelFilter: 'all',
        eventTypeFilter: 'all',
        /** @type {string[]} */
        availableEventTypes: [],

        /** @type {string} Selected date for jump-to-date (YYYY-MM-DD) */
        selectedDate: '',

        PAGE_SIZE: 50,

        // === LIFECYCLE ===

        openModal() {
            this.isOpen = true;
            this.reset();
            this.loadEvents();
        },

        closeModal() {
            this.isOpen = false;
        },

        reset() {
            this.events = [];
            this.filteredEvents = [];
            this.hasMore = true;
            this.error = null;
            this.selectedDate = '';
        },

        // === DATA LOADING ===

        async loadEvents() {
            this.isLoading = true;
            this.error = null;
            this.events = [];
            this.hasMore = true;
            try {
                const data = await this._fetchPage();
                this.events = data;
                this.hasMore = data.length >= this.PAGE_SIZE;
                this.updateAvailableEventTypes();
                this.applyFilters();
            } catch (err) {
                this.error = `Failed to load events: ${err instanceof Error ? err.message : err}`;
            } finally {
                this.isLoading = false;
            }
        },

        async loadMore() {
            if (this.isLoadingMore || !this.hasMore) return;
            const lastId = this._lastId();
            if (lastId === null) return;

            this.isLoadingMore = true;
            try {
                const data = await this._fetchPage(lastId);
                if (data.length === 0) {
                    this.hasMore = false;
                } else {
                    this.events = [...this.events, ...data];
                    this.hasMore = data.length >= this.PAGE_SIZE;
                    this.updateAvailableEventTypes();
                    this.applyFilters();
                }
            } catch (err) {
                console.error('Failed to load more events:', err);
            } finally {
                this.isLoadingMore = false;
            }
        },

        /**
         * @param {number} [beforeId]
         * @returns {Promise<LogEvent[]>}
         */
        async _fetchPage(beforeId) {
            const params = new URLSearchParams();
            params.append('limit', String(this.PAGE_SIZE));
            if (this.levelFilter !== 'all') {
                params.append('level', this.levelFilter);
            }
            if (this.selectedDate) {
                params.append('from_date', `${this.selectedDate}T00:00:00`);
            }
            if (beforeId !== undefined) {
                params.append('before_id', String(beforeId));
            }
            const response = await fetch(`/api/events/?${params.toString()}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            return response.json();
        },

        /** @returns {number|null} */
        _lastId() {
            if (this.events.length === 0) return null;
            return this.events[this.events.length - 1].id;
        },

        // === INFINITE SCROLL ===

        handleScroll(event) {
            const el = event.target;
            const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 200;
            if (nearBottom && !this.isLoadingMore && this.hasMore) {
                this.loadMore();
            }
        },

        // === FILTERS ===

        get computedStats() {
            const total = this.events.length;
            let errors = 0;
            let warnings = 0;
            for (const event of this.events) {
                if (event.level === 'ERROR') errors++;
                else if (event.level === 'WARNING') warnings++;
            }
            return { total_events: total, error_count: errors, warning_count: warnings };
        },

        updateAvailableEventTypes() {
            const types = [...new Set(this.events.map((/** @type {LogEvent} */ e) => e.event_type))];
            this.availableEventTypes = types.sort();
        },

        applyFilters() {
            let filtered = this.events;
            if (this.eventTypeFilter !== 'all') {
                filtered = filtered.filter(e => e.event_type === this.eventTypeFilter);
            }
            this.filteredEvents = filtered;
        },

        setLevelFilter(level) {
            this.levelFilter = level;
            this.loadEvents();
        },

        setEventTypeFilter(eventType) {
            this.eventTypeFilter = eventType;
            this.applyFilters();
        },

        // === DATE PICKER ===

        jumpToDate() {
            if (!this.selectedDate) {
                this.selectedDate = '';
                this.loadEvents();
                return;
            }
            this.loadEvents();
        },

        clearDate() {
            this.selectedDate = '';
            this.loadEvents();
        },

        // === DOWNLOAD ===

        downloadDay() {
            const day = this.selectedDate || new Date().toISOString().slice(0, 10);
            window.open(`/api/events/download?day=${day}`, '_blank');
        },

        // === REFRESH ===

        refresh() {
            this.reset();
            this.loadEvents();
        },

        // === UI HELPERS ===

        getLevelBadgeColor(level) {
            switch (level.toLowerCase()) {
                case 'error': return 'bg-red-500 text-white';
                case 'warning': return 'bg-yellow-500 text-black';
                case 'info': return 'bg-blue-500 text-white';
                default: return 'bg-gray-500 text-white';
            }
        },

        getEventTypeIcon(eventType) {
            if (eventType.includes('Network')) return '\u{1F310}';
            if (eventType.includes('Storage')) return '\u{1F4BE}';
            if (eventType.includes('Mount')) return '\u{1F517}';
            if (eventType.includes('File')) return '\u{1F4C4}';
            if (eventType.includes('Scanner')) return '\u{1F50D}';
            if (eventType.includes('Destination')) return '\u{1F3AF}';
            return '\u{1F4CA}';
        },

        formatTimestamp(timestamp) {
            const date = new Date(timestamp);
            return date.toLocaleString('da-DK', {
                year: 'numeric', month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit', second: '2-digit'
            });
        },

        formatRelativeTime(timestamp) {
            const now = new Date();
            const eventTime = new Date(timestamp);
            const diffInSeconds = Math.floor((now.getTime() - eventTime.getTime()) / 1000);
            if (diffInSeconds < 60) return `${diffInSeconds} sek siden`;
            if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)} min siden`;
            if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)} timer siden`;
            return `${Math.floor(diffInSeconds / 86400)} dage siden`;
        },

        getFormattedDetails(details) {
            if (!details || Object.keys(details).length === 0) return null;
            return Object.entries(details).map(([key, value]) => `${key}: ${value}`).join(', ');
        }
    });
});