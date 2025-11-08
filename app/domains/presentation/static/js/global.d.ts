
// Define the LogFile type to be used globally
type LogFile = {
    filename: string;
    size_mb: number;
    size_bytes?: number;
    lines?: number;
};

interface UIHelpers {
    formatSizeFromGB(gb: number | null | undefined): string;
}

// Extend the global Window interface
declare global {
    interface Window {
        openLogViewerModal: () => void;
        closeLogViewerModal: () => void;
        loadLogFile: (logFile: LogFile) => void;
        loadMoreForward: () => void;
        loadMoreBackward: () => void;
        downloadLogFile: (filename: string) => void;

        // Functions from settingsStore.js
        openSettingsModal: () => void;
        closeSettingsModal: () => void;
        reloadConfig: () => void;
        restartApplication: () => void;
        toggleScanner: () => void;
        UIHelpers: UIHelpers;
    }
}

// Export an empty object to make this a module
export {};
