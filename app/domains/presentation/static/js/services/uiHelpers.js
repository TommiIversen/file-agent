/**
 * UI Helpers Service - UI Utility Functions
 *
 * Collection of utility functions for UI formatting, calculations,
 * and common UI operations used across components.
 */

class UIHelpers {

    /**
     * Format timestamp to Danish locale date and time string
     * @param {string} timestamp
     */
    static formatDateTime(timestamp) {
        if (!timestamp) return '-';
        try {
            return new Date(timestamp).toLocaleString('da-DK');
        } catch (error) {
            console.warn('Invalid timestamp:', timestamp);
            return '-';
        }
    }

    /**
     * Format timestamp to custom format: 20/3 20:33:18
     * @param {string} timestamp
     */
    static formatCustomDateTime(timestamp) {
        if (!timestamp) return '-';
        try {
            const date = new Date(timestamp);
            const day = date.getDate();
            const month = date.getMonth() + 1; // Months are 0-indexed
            const hours = date.getHours().toString().padStart(2, '0');
            const minutes = date.getMinutes().toString().padStart(2, '0');
            const seconds = date.getSeconds().toString().padStart(2, '0');

            return `${day}/${month} ${hours}:${minutes}:${seconds}`;
        } catch (error) {
            console.warn('Invalid timestamp:', timestamp);
            return '-';
        }
    }

    /**
     * Get progress bar width style for file
     * @param {TrackedFile} file
     */
    static getProgressWidth(file) {
        if (!file) return 'width: 0%';

        switch (file.status) {
            case 'Discovered':
            case 'Growing':
            case 'Ready':
            case 'ReadyToStartGrowing':
            case 'InQueue':
            case 'WaitingForSpace':
            case 'WaitingForNetwork':
                return 'width: 0%';
            case 'Copying':
            case 'GrowingCopy':
                return `width: ${file.copy_progress || 0}%`;
            case 'PausedInQueue':
                return 'width: 0%';
            case 'PausedCopying':
            case 'PausedGrowingCopy':
                return `width: ${file.copy_progress || 0}%`;
            case 'Completed':
            case 'CompletedDeleteFailed':
                return 'width: 100%';
            case 'Failed':
            case 'SpaceError':
                return 'width: 100%';
            default:
                return 'width: 0%';
        }
    }

    /**
     * Get progress bar color class for file status
     * @param {TrackedFile} file
     */
    static getProgressColor(file) {
        if (!file) return 'bg-gray-600';

        switch (file.status) {
            case 'Discovered':
            case 'Growing':
            case 'Ready':
            case 'ReadyToStartGrowing':
            case 'InQueue':
            case 'WaitingForSpace':
                return 'bg-gray-600';
            case 'WaitingForNetwork':
                return 'bg-orange-600';  // Distinct color for network waiting
            case 'Copying':
                return 'bg-blue-600';
            case 'GrowingCopy':
                return 'bg-purple-600';
            case 'PausedInQueue':
            case 'PausedCopying':
            case 'PausedGrowingCopy':
                return 'bg-yellow-600';  // Distinct color for paused operations
            case 'Completed':
                return 'bg-green-600';
            case 'CompletedDeleteFailed':
                return 'bg-yellow-500';  // A distinct color for this state
            case 'Failed':
            case 'SpaceError':
                return 'bg-red-600';
            default:
                return 'bg-gray-600';
        }
    }

    /**
     * Get progress text for file
     * @param {TrackedFile} file
     */
    static getProgressText(file) {
        if (!file) return '0%';

        switch (file.status) {
            case 'Discovered':
            case 'Growing':
            case 'Ready':
            case 'ReadyToStartGrowing':
            case 'InQueue':
            case 'WaitingForSpace':
            case 'WaitingForNetwork':
                return '0%';
            case 'Copying':
                return `${(file.copy_progress || 0).toFixed(1)}%`;
            case 'GrowingCopy':
                // Show both copy progress and buffer status for growing files
                const progress = (file.copy_progress || 0).toFixed(1);
                const buffer = file.buffer_percent ? ` (Buffer: ${file.buffer_percent.toFixed(0)}%)` : '';
                return `${progress}%${buffer}`;
            case 'Completed':
                return '100%';
            case 'Failed':
            case 'SpaceError':
                return '0%';
            default:
                return '0%';
        }
    }

    /**
     * Get status badge color class for file status
     * @param {FileStatus} status
     */
    static getStatusBadgeColor(status) {
        switch (status) {
            case 'Discovered':
                return 'bg-blue-600';
            case 'Growing':
                return 'bg-orange-600';
            case 'ReadyToStartGrowing':
                return 'bg-yellow-600';
            case 'Ready':
                return 'bg-green-600';
            case 'InQueue':
                return 'bg-yellow-600';
            case 'Copying':
                return 'bg-blue-700';
            case 'GrowingCopy':
                return 'bg-purple-600';
            case 'PausedInQueue':
                return 'bg-yellow-500 animate-pulse';
            case 'PausedCopying':
                return 'bg-blue-500 animate-pulse';
            case 'PausedGrowingCopy':
                return 'bg-purple-500 animate-pulse';
            case 'Completed':
                return 'bg-green-700';
            case 'CompletedDeleteFailed':
                return 'bg-yellow-600';
            case 'Failed':
                return 'bg-red-600';
            case 'Removed':
                return 'bg-orange-500';
            case 'WaitingForSpace':
                return 'bg-orange-600';
            case 'WaitingForNetwork':
                return 'bg-indigo-600';  // Network waiting - distinct color
            case 'SpaceError':
                return 'bg-purple-600';
            default:
                return 'bg-gray-600';
        }
    }

    /**
     * Extract filename from full path
     * @param {string} filePath
     */
    static getFileName(filePath) {
        if (!filePath) return '';
        return filePath.split(/[/\\]/).pop();
    }

    /** @type {Map<string, string>} */
    static _lucideCache = new Map();

    /**
     * Render a Lucide icon as inline SVG string.
     * Uses lucide.icons data directly — no MutationObserver or createIcons() needed.
     * @param {string} name - kebab-case icon name (e.g. "file-text", "settings")
     * @param {string} [classes=''] - CSS classes for the SVG element
     * @returns {string} SVG markup string
     */
    static icon(name, classes = '') {
        const key = `${name}|${classes}`;
        const cached = this._lucideCache.get(key);
        if (cached) return cached;

        // Convert kebab-case to PascalCase for lucide.icons lookup
        const pascalName = name.replace(/(^|-)([a-z0-9])/g, (_, __, c) => c.toUpperCase());
        const iconData = lucide?.icons?.[pascalName];
        if (!iconData) {
            console.warn(`[UIHelpers.icon] Unknown icon: "${name}" (lookup: ${pascalName})`);
            return '';
        }

        const buildEl = (/** @type {[string, Record<string, string>?]} */ [tag, attrs]) => {
            const a = Object.entries(attrs || {}).map(([k, v]) => `${k}="${v}"`).join(' ');
            return `<${tag}${a ? ' ' + a : ''}/>`;
        };

        const paths = iconData.map(buildEl).join('');
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-0.125em" class="${classes}">${paths}</svg>`;
        this._lucideCache.set(key, svg);
        return svg;
    }

    /** @type {Map<string, string>} */
    static _iconCache = new Map();

    /**
     * Get inline SVG icon for file type (avoids lucide createIcons loop)
     * @param {string} filePath
     */
    static getFileTypeIconSvg(filePath) {
        const ext = ((filePath || '').split('.').pop() || '').toLowerCase();
        if (this._iconCache.has(ext)) return this._iconCache.get(ext);

        let color, paths;
        if (['wav', 'mp3', 'aac', 'flac'].includes(ext)) {
            color = '#c084fc';
            paths = '<path d="M2 10v3"/><path d="M6 6v11"/><path d="M10 3v18"/><path d="M14 8v7"/><path d="M18 5v13"/><path d="M22 10v3"/>';
        } else if (['mxf', 'mp4', 'mov', 'avi'].includes(ext)) {
            color = '#60a5fa';
            paths = '<path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.934a.5.5 0 0 0-.777-.416L16 11"/><rect x="2" y="6" width="14" height="12" rx="2"/>';
        } else {
            color = '#9ca3af';
            paths = '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>';
        }

        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
        this._iconCache.set(ext, svg);
        return svg;
    }

    /**
     * Format file size from MB value
     * @param {number} sizeMB
     */
    static formatFileSizeMB(sizeMB) {
        if (!sizeMB || sizeMB === 0) return '0 MB';

        if (sizeMB < 1) {
            return `${(sizeMB * 1024).toFixed(1)} KB`;
        } else if (sizeMB < 1024) {
            return `${sizeMB.toFixed(1)} MB`;
        } else {
            return `${(sizeMB / 1024).toFixed(2)} GB`;
        }
    }

    /**
     * Get user-friendly status text
     * @param {FileStatus} status
     */
    static getFriendlyStatus(status) {
        switch (status) {
            case 'Discovered':
                return 'Discovered';
            case 'Growing':
                return 'Growing';
            case 'ReadyToStartGrowing':
                return 'Ready (Growing)';
            case 'Ready':
                return 'Ready';
            case 'InQueue':
                return 'In Queue';
            case 'Copying':
                return 'Copying';
            case 'GrowingCopy':
                return 'Growing Copy';
            case 'PausedInQueue':
                return '⏸️ Paused (Queue)';
            case 'PausedCopying':
                return '⏸️ Paused (Copy)';
            case 'PausedGrowingCopy':
                return '⏸️ Paused (Growing)';
            case 'Completed':
                return 'Completed';
            case 'CompletedDeleteFailed':
                return 'Delete Failed';
            case 'Failed':
                return 'Failed';
            case 'WaitingForSpace':
                return 'Waiting (Space)';
            case 'WaitingForNetwork':
                return 'Waiting (Network)';  // Clear label for network waiting
            case 'SpaceError':
                return 'Space Error';
            default:
                return status;
        }
    }

    /**
     * Check if file is a growing file
     * @param {TrackedFile} file
     */
    static isGrowingFile(file) {
        return file && ['Growing', 'ReadyToStartGrowing', 'GrowingCopy', 'PausedGrowingCopy'].includes(file.status);
    }

    /**
     * Get growing file indicator icon
     * @param {TrackedFile} file
     */
    static getGrowingFileIcon(file) {
        if (!this.isGrowingFile(file)) return '';

        switch (file.status) {
            case 'Growing':
                return '📈'; // Growing chart
            case 'ReadyToStartGrowing':
                return '⚡'; // Ready to start
            case 'GrowingCopy':
                return '🔄'; // Active copy
            default:
                return '📊'; // Generic growing indicator
        }
    }

    /**
     * Format bytes copied for growing files
     * @param {number} bytesCopied
     * @param {number} totalSize
     */
    static formatBytesCopied(bytesCopied, totalSize) {
        if (!bytesCopied || bytesCopied === 0) return '0 MB';

        const copiedMB = bytesCopied / (1024 * 1024);
        const totalMB = totalSize ? totalSize / (1024 * 1024) : 0;

        if (totalMB > 0) {
            return `${this._formatMBSmart(copiedMB)} / ${this._formatMBSmart(totalMB)}`;
        } else {
            return this._formatMBSmart(copiedMB);
        }
    }

    /**
     * Format MB value to appropriate unit (MB, GB, TB) with 1 decimal
     * @param {number} mb - value in megabytes
     */
    static _formatMBSmart(mb) {
        if (mb >= 1024 * 1024) return `${(mb / (1024 * 1024)).toFixed(1)} TB`;
        if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
        return `${mb.toFixed(1)} MB`;
    }

    /**
     * Format size from GB to a human-readable string (GB, TB, PB).
     * @param {number | null | undefined} sizeGB
     */
    static formatSizeFromGB(sizeGB) {
        if (sizeGB === null || typeof sizeGB === 'undefined' || isNaN(sizeGB)) {
            return '0 GB';
        }
        if (sizeGB === 0) return '0 GB';

        const sizeTB = sizeGB / 1024;
        const sizePB = sizeTB / 1024;

        if (sizePB >= 1) {
            return `${sizePB.toFixed(2)} PB`;
        } else if (sizeTB >= 1) {
            return `${sizeTB.toFixed(2)} TB`;
        } else {
            return `${sizeGB.toFixed(1)} GB`;
        }
    }
}

// Make UIHelpers available globally
window.UIHelpers = UIHelpers;

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = UIHelpers;
}