// @ts-check

/**
 * Performance Store - System Metrics Management
 *
 * Tracks CPU, memory, disk, and network metrics.
 * Supports live updates via WebSocket and lazy-fetches full history
 * when the performance dialog is opened.
 */

// Chart instances stored OUTSIDE Alpine reactive system to avoid proxy conflicts
const _perfCharts = { cpu: null, net: null, cores: null };

document.addEventListener('alpine:init', () => {
    Alpine.store('perf', {
        // Current system values (latest sample)
        system: {
            cpu: 0,
            mem: 0,
            disk: 0,
            net_rx: 0,
            net_tx: 0,
            cores: [],
        },

        // Time-series history (max ~60 samples = 10 min)
        history: [],

        // Dialog open state
        isOpen: false,

        // Whether full history has been fetched
        _historyLoaded: false,

        /**
         * Handle a live perf_sample from WebSocket
         * @param {object} sample
         */
        handlePerfSample(sample) {
            // Update current values
            this.system.cpu = sample.cpu ?? 0;
            this.system.mem = sample.mem ?? 0;
            this.system.disk = sample.disk ?? 0;
            this.system.net_rx = sample.net_rx ?? 0;
            this.system.net_tx = sample.net_tx ?? 0;
            this.system.cores = sample.cores ?? [];

            // Append to history (keep max 60)
            this.history.push(sample);
            if (this.history.length > 60) {
                this.history.shift();
            }

            // Update live charts only if dialog is open
            if (this.isOpen) {
                this._updateCharts(sample);
            }
        },

        /**
         * Fetch full history from REST API (called when dialog opens)
         */
        async fetchHistory() {
            if (this._historyLoaded) return;
            try {
                const res = await fetch('/api/system-metrics/history');
                if (!res.ok) return;
                const data = await res.json();
                if (data.history && data.history.length > 0) {
                    this.history = data.history;
                    // Set current from last sample
                    const last = data.history[data.history.length - 1];
                    this.system.cpu = last.cpu ?? 0;
                    this.system.mem = last.mem ?? 0;
                    this.system.disk = last.disk ?? 0;
                    this.system.net_rx = last.net_rx ?? 0;
                    this.system.net_tx = last.net_tx ?? 0;
                    this.system.cores = last.cores ?? [];
                }
                this._historyLoaded = true;
            } catch (e) {
                console.error('Failed to fetch perf history:', e);
            }
        },

        /**
         * Open performance dialog — fetches history and initializes charts
         */
        async openDialog() {
            await this.fetchHistory();
            this.isOpen = true;
            // Wait for Alpine to render the DOM, then init charts
            setTimeout(() => this._initCharts(), 50);
        },

        /**
         * Close performance dialog — destroy charts to free memory
         */
        closeDialog() {
            this.isOpen = false;
            this.destroyCharts();
        },

        /**
         * Called when dialog closes — destroy charts to free memory
         */
        destroyCharts() {
            Object.keys(_perfCharts).forEach(key => {
                if (_perfCharts[key]) {
                    _perfCharts[key].destroy();
                    _perfCharts[key] = null;
                }
            });
        },

        /**
         * Initialize Chart.js charts inside the dialog
         */
        _initCharts() {
            this._initCpuMemChart();
            this._initNetChart();
            this._initCoresChart();
        },

        _initCpuMemChart() {
            const ctx = document.getElementById('perf-cpu-chart');
            if (!ctx || _perfCharts.cpu) return;

            const labels = this.history.map((_, i) => {
                const secsAgo = (this.history.length - 1 - i) * 10;
                return secsAgo > 0 ? `-${Math.round(secsAgo / 60)}m` : 'now';
            });

            _perfCharts.cpu = new Chart(ctx, {
                type: 'line',
                data: {
                    labels,
                    datasets: [
                        {
                            label: 'CPU %',
                            data: this.history.map(s => s.cpu),
                            borderColor: 'rgba(59, 130, 246, 1)',
                            backgroundColor: 'rgba(59, 130, 246, 0.1)',
                            borderWidth: 2,
                            fill: true,
                            tension: 0.3,
                            pointRadius: 0,
                        },
                        {
                            label: 'MEM %',
                            data: this.history.map(s => s.mem),
                            borderColor: 'rgba(168, 85, 247, 1)',
                            backgroundColor: 'rgba(168, 85, 247, 0.1)',
                            borderWidth: 2,
                            fill: true,
                            tension: 0.3,
                            pointRadius: 0,
                        },
                        {
                            label: 'DISK %',
                            data: this.history.map(s => s.disk),
                            borderColor: 'rgba(234, 179, 8, 1)',
                            backgroundColor: 'rgba(234, 179, 8, 0.05)',
                            borderWidth: 1.5,
                            fill: false,
                            tension: 0.3,
                            pointRadius: 0,
                            borderDash: [4, 2],
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        y: { min: 0, max: 100, ticks: { callback: v => v + '%' } },
                        x: { display: true, ticks: { maxTicksLimit: 6 } },
                    },
                    plugins: { legend: { position: 'top', labels: { boxWidth: 12 } } },
                },
            });
        },

        _initNetChart() {
            const ctx = document.getElementById('perf-net-chart');
            if (!ctx || _perfCharts.net) return;

            const labels = this.history.map((_, i) => {
                const secsAgo = (this.history.length - 1 - i) * 10;
                return secsAgo > 0 ? `-${Math.round(secsAgo / 60)}m` : 'now';
            });

            _perfCharts.net = new Chart(ctx, {
                type: 'line',
                data: {
                    labels,
                    datasets: [
                        {
                            label: '↓ RX Mbps',
                            data: this.history.map(s => s.net_rx),
                            borderColor: 'rgba(34, 197, 94, 1)',
                            backgroundColor: 'rgba(34, 197, 94, 0.1)',
                            borderWidth: 2,
                            fill: true,
                            tension: 0.3,
                            pointRadius: 0,
                        },
                        {
                            label: '↑ TX Mbps',
                            data: this.history.map(s => s.net_tx),
                            borderColor: 'rgba(249, 115, 22, 1)',
                            backgroundColor: 'rgba(249, 115, 22, 0.1)',
                            borderWidth: 2,
                            fill: true,
                            tension: 0.3,
                            pointRadius: 0,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        y: { min: 0, ticks: { callback: v => v.toFixed(1) } },
                        x: { display: true, ticks: { maxTicksLimit: 6 } },
                    },
                    plugins: { legend: { position: 'top', labels: { boxWidth: 12 } } },
                },
            });
        },

        _initCoresChart() {
            const ctx = document.getElementById('perf-cores-chart');
            if (!ctx || _perfCharts.cores) return;

            const latest = this.history.length > 0
                ? this.history[this.history.length - 1]
                : { cores: [] };
            const coreData = latest.cores || [];
            const labels = coreData.map((_, i) => `C${i}`);

            _perfCharts.cores = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [{
                        label: 'Core %',
                        data: coreData,
                        backgroundColor: coreData.map(v =>
                            v > 80 ? 'rgba(239, 68, 68, 0.7)' :
                            v > 50 ? 'rgba(234, 179, 8, 0.7)' :
                            'rgba(59, 130, 246, 0.7)'
                        ),
                        borderWidth: 0,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    scales: {
                        y: { min: 0, max: 100, ticks: { callback: v => v + '%' } },
                        x: { display: true },
                    },
                    plugins: { legend: { display: false } },
                },
            });
        },

        /**
         * Update existing charts with a new sample (live update)
         * @param {object} sample
         */
        _updateCharts(sample) {
            try {
                if (_perfCharts.cpu && _perfCharts.cpu.canvas) {
                    const chart = _perfCharts.cpu;
                    chart.data.labels.push('now');
                    chart.data.labels.shift();
                    chart.data.datasets[0].data.push(sample.cpu);
                    chart.data.datasets[0].data.shift();
                    chart.data.datasets[1].data.push(sample.mem);
                    chart.data.datasets[1].data.shift();
                    chart.data.datasets[2].data.push(sample.disk);
                    chart.data.datasets[2].data.shift();
                    chart.update('none');
                }

                if (_perfCharts.net && _perfCharts.net.canvas) {
                    const chart = _perfCharts.net;
                    chart.data.labels.push('now');
                    chart.data.labels.shift();
                    chart.data.datasets[0].data.push(sample.net_rx);
                    chart.data.datasets[0].data.shift();
                    chart.data.datasets[1].data.push(sample.net_tx);
                    chart.data.datasets[1].data.shift();
                    chart.update('none');
                }

                if (_perfCharts.cores && _perfCharts.cores.canvas && sample.cores) {
                    const chart = _perfCharts.cores;
                    chart.data.datasets[0].data = sample.cores;
                    chart.data.datasets[0].backgroundColor = sample.cores.map(v =>
                        v > 80 ? 'rgba(239, 68, 68, 0.7)' :
                        v > 50 ? 'rgba(234, 179, 8, 0.7)' :
                        'rgba(59, 130, 246, 0.7)'
                    );
                    chart.data.labels = sample.cores.map((_, i) => `C${i}`);
                    chart.update('none');
                }
            } catch (e) {
                // Chart may be in a transitional state during open/close
                console.debug('Chart update skipped:', e.message);
            }
        },
    });
});
