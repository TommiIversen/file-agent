/**
 * UI Helpers Service - UI Utility Functions
 * 
 * Collection of utility functions for UI formatting, calculations,
 * and common UI operations used across components.
 */

class UIHelpers {
    /**
     * Format timestamp to Danish locale time string
     */
    static formatTime(timestamp) {
        if (!timestamp) return '-';
        try {
            return new Date(timestamp).toLocaleTimeString('da-DK');
        } catch (error) {
            console.warn('Invalid timestamp:', timestamp);
            return '-';
        }
    }
    
    /**
     * Format timestamp to Danish locale date and time string
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
     * Get progress bar width style for file
     */
    static getProgressWidth(file) {
        if (!file) return 'width: 0%';
        
        switch (file.status) {
            case 'Discovered':
            case 'Ready':
            case 'InQueue':
                return 'width: 0%';
            case 'Copying':
                return `width: ${file.copy_progress || 0}%`;
            case 'Completed':
                return 'width: 100%';
            case 'Failed':
                return 'width: 100%';
            default:
                return 'width: 0%';
        }
    }
    
    /**
     * Get progress bar color class for file status
     */
    static getProgressColor(file) {
        if (!file) return 'bg-gray-600';
        
        switch (file.status) {
            case 'Discovered':
            case 'Ready':
            case 'InQueue':
            case 'WaitingForSpace':
                return 'bg-gray-600';
            case 'Copying':
                return 'bg-blue-600';
            case 'Completed':
                return 'bg-green-600';
            case 'Failed':
            case 'SpaceError':
                return 'bg-red-600';
            default:
                return 'bg-gray-600';
        }
    }
    
    /**
     * Get progress text for file
     */
    static getProgressText(file) {
        if (!file) return '0%';
        
        switch (file.status) {
            case 'Discovered':
            case 'Ready':
            case 'InQueue':
            case 'WaitingForSpace':
                return '0%';
            case 'Copying':
                return `${(file.copy_progress || 0).toFixed(1)}%`;
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
     */
    static getStatusBadgeColor(status) {
        switch (status) {
            case 'Discovered': return 'bg-blue-600';
            case 'Ready': return 'bg-green-600';
            case 'InQueue': return 'bg-yellow-600';
            case 'Copying': return 'bg-blue-700';
            case 'Completed': return 'bg-green-700';
            case 'Failed': return 'bg-red-600';
            case 'WaitingForSpace': return 'bg-orange-600';
            case 'SpaceError': return 'bg-purple-600';
            default: return 'bg-gray-600';
        }
    }
    
    /**
     * Extract filename from full path
     */
    static getFileName(filePath) {
        if (!filePath) return '';
        return filePath.split(/[/\\]/).pop();
    }
    
    /**
     * Format file size in MB
     */
    static formatFileSize(sizeBytes) {
        if (!sizeBytes || sizeBytes === 0) return '0 MB';
        
        const sizeMB = sizeBytes / (1024 * 1024);
        
        if (sizeMB < 1) {
            const sizeKB = sizeBytes / 1024;
            return `${sizeKB.toFixed(1)} KB`;
        } else if (sizeMB < 1024) {
            return `${sizeMB.toFixed(1)} MB`;
        } else {
            const sizeGB = sizeMB / 1024;
            return `${sizeGB.toFixed(2)} GB`;
        }
    }
    
    /**
     * Format file size from MB value
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
     * Calculate duration between two timestamps
     */
    static calculateDuration(startTime, endTime) {
        if (!startTime) return '-';
        
        const start = new Date(startTime);
        const end = endTime ? new Date(endTime) : new Date();
        const durationMs = end - start;
        
        if (durationMs < 0) return '-';
        
        const seconds = Math.floor(durationMs / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        
        if (hours > 0) {
            return `${hours}t ${minutes % 60}m`;
        } else if (minutes > 0) {
            return `${minutes}m ${seconds % 60}s`;
        } else {
            return `${seconds}s`;
        }
    }
    
    /**
     * Get relative time string (e.g., "2 minutes ago")
     */
    static getRelativeTime(timestamp) {
        if (!timestamp) return '-';
        
        const now = new Date();
        const time = new Date(timestamp);
        const diffMs = now - time;
        
        if (diffMs < 0) return 'i fremtiden';
        
        const seconds = Math.floor(diffMs / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);
        
        if (days > 0) {
            return `${days} dag${days !== 1 ? 'e' : ''} siden`;
        } else if (hours > 0) {
            return `${hours} time${hours !== 1 ? 'r' : ''} siden`;
        } else if (minutes > 0) {
            return `${minutes} minut${minutes !== 1 ? 'ter' : ''} siden`;
        } else if (seconds > 30) {
            return `${seconds} sekunder siden`;
        } else {
            return 'lige nu';
        }
    }
    
    /**
     * Debounce function calls
     */
    static debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
    
    /**
     * Throttle function calls
     */
    static throttle(func, limit) {
        let inThrottle;
        return function executedFunction(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }
    
    /**
     * Copy text to clipboard
     */
    static async copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (error) {
            console.error('Failed to copy to clipboard:', error);
            return false;
        }
    }
    
    /**
     * Generate CSS classes for status indicators
     */
    static getStatusClasses(status, type = 'badge') {
        const baseClasses = {
            badge: 'text-green-100 truncate text-center py-1 px-3 rounded-full text-xs font-bold',
            indicator: 'w-3 h-3 rounded-full',
            text: 'text-sm font-medium'
        };
        
        const statusColors = {
            'Discovered': 'bg-blue-600 text-blue-100',
            'Ready': 'bg-green-600 text-green-100',
            'InQueue': 'bg-yellow-600 text-yellow-100',
            'Copying': 'bg-blue-700 text-blue-100',
            'Completed': 'bg-green-700 text-green-100',
            'Failed': 'bg-red-600 text-red-100',
            'WaitingForSpace': 'bg-orange-600 text-orange-100',
            'SpaceError': 'bg-purple-600 text-purple-100'
        };
        
        const baseClass = baseClasses[type] || baseClasses.badge;
        const statusClass = statusColors[status] || 'bg-gray-600 text-gray-100';
        
        return `${baseClass} ${statusClass}`;
    }
}

// Make UIHelpers available globally
window.UIHelpers = UIHelpers;

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = UIHelpers;
}