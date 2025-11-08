// @ts-check

/**
 * @typedef {'Discovered'|'Ready'|'InQueue'|'Copying'|'Completed'|'CompletedDeleteFailed'|'Failed'|'Removed'|'Growing'|'ReadyToStartGrowing'|'GrowingCopy'|'WaitingForSpace'|'SpaceError'|'WaitingForNetwork'|'PausedInQueue'|'PausedCopying'|'PausedGrowingCopy'} FileStatus
 */

/**
 * @typedef {object} TrackedFile
 * @property {string} id
 * @property {string} file_path
 * @property {FileStatus} status
 * @property {number} file_size
 * @property {string} [last_write_time]
 * @property {number} copy_progress
 * @property {string} [error_message]
 * @property {number} retry_count
 * @property {string} discovered_at
 * @property {string} [creation_time]
 * @property {string} [started_copying_at]
 * @property {string} [completed_at]
 * @property {string} [failed_at]
 * @property {string} [space_error_at]
 * @property {string} [destination_path]
 * @property {number} growth_rate_mbps
 * @property {number} bytes_copied
 * @property {number} copy_speed_mbps
 * @property {string} [last_growth_check]
 * @property {number} previous_file_size
 * @property {number} first_seen_size
 * @property {string} [growth_stable_since]
 * @property {object} [retry_info]
 * @property {number} [buffer_percent]
 */

/**
 * UI Helpers Service - UI Utility Functions
 *
 * Collection of utility functions for UI formatting, calculations,
 * and common UI operations used across components.
 */
class UIHelpers {

    /**
     * Format timestamp to Danish locale date and time string
     * @param {string | number | Date | undefined} timestamp
     * @returns {string}
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
     * @param {string | number | Date | undefined} timestamp
     * @returns {string}
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
     * @param {TrackedFile | null | undefined} file
     * @returns {string}
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
     * @param {TrackedFile | null | undefined} file
     * @returns {string}
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
     * @param {TrackedFile | null | undefined} file
     * @returns {string}
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
     * @param {FileStatus | string | undefined} status
     * @returns {string}
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
     * @param {string | undefined} filePath
     * @returns {string}
     */
    static getFileName(filePath) {
        if (!filePath) return '';
        return filePath.split(/[/\\]/).pop() || '';
    }

    /**
     * Format file size from MB value
     * @param {number | undefined} sizeMB
     * @returns {string}
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
     * @param {FileStatus | string | undefined} status
     * @returns {string}
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
                return status || '';
        }
    }

    /**
     * Check if file is a growing file
     * @param {TrackedFile | null | undefined} file
     * @returns {boolean}
     */
    static isGrowingFile(file) {
        return !!(file && ['Growing', 'ReadyToStartGrowing', 'GrowingCopy', 'PausedGrowingCopy'].includes(file.status));
    }

    /**
     * Get growing file indicator icon
     * @param {TrackedFile | null | undefined} file
     * @returns {string}
     */
    static getGrowingFileIcon(file) {
        if (!file || !this.isGrowingFile(file)) return '';

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
     * @param {number | undefined} bytesCopied
     * @param {number | undefined} totalSize
     * @returns {string}
     */
    static formatBytesCopied(bytesCopied, totalSize) {
        if (!bytesCopied || bytesCopied === 0) return '0 MB';

        const copiedMB = bytesCopied / (1024 * 1024);
        const totalMB = totalSize ? totalSize / (1024 * 1024) : 0;

        if (totalMB > 0) {
            return `${copiedMB.toFixed(1)} / ${totalMB.toFixed(1)} MB`;
        } else {
            return `${copiedMB.toFixed(1)} MB`;
        }
    }

    /**
     * Format size from GB to a human-readable string (GB, TB, PB).
     * @param {number | null | undefined} sizeGB
     * @returns {string}
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
// @ts-ignore
window.UIHelpers = UIHelpers;

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = UIHelpers;
}
