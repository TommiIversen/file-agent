
// Extend the global Window interface
declare global {
    type LogFile = {
        filename: string;
        size_mb: number;
        size_bytes?: number;
        lines?: number;
    };

    class UIHelpers {
        static formatDateTime(timestamp: string): string;
        static formatCustomDateTime(timestamp: string): string;
        static getProgressWidth(file: TrackedFile): string;
        static getProgressColor(file: TrackedFile): string;
        static getProgressText(file: TrackedFile): string;
        static getStatusBadgeColor(status: FileStatus): string;
        static getFileName(filePath: string): string | undefined;
        static formatFileSizeMB(sizeMB: number): string;
        static getFriendlyStatus(status: FileStatus): string;
        static isGrowingFile(file: TrackedFile): boolean;
        static getGrowingFileIcon(file: TrackedFile): string;
        static formatBytesCopied(bytesCopied: number, totalSize: number): string;
        static formatSizeFromGB(sizeGB: number | null | undefined): string;
    }

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

        messageHandler?: MessageHandler;
        UIHelpers?: typeof UIHelpers;
    }

    // Declare Alpine as a global variable
    const Alpine: any;

    type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';

    type MessageHandler = {
        handleMessage: (message: Object) => void;
    };

    type CustomWindow = Window & typeof globalThis & { messageHandler?: MessageHandler };

    type SortField = 'name' | 'size' | 'created' | 'modified' | 'type';

    type SortDirection = 'asc' | 'desc';

    type ViewMode = 'tree' | 'flat';

    type ScanType = 'source' | 'destination';

    type DirectoryItem = {
        name: string;
        path: string;
        is_directory: boolean;
        is_hidden: boolean;
        size_bytes: number | null;
        created_time: string | null;
        modified_time: string | null;
        parent_path: string | null;
        depth_level: number;
        relative_path: string;
        children: DirectoryItem[] | null;
    };

    type DirectoryScanResult = {
        path: string;
        is_accessible: boolean;
        items: DirectoryItem[];
        tree: DirectoryItem[];
        total_items: number;
        total_files: number;
        total_directories: number;
        scan_duration_seconds: number;
        error_message: string | null;
    };

    type LogEvent = {
        timestamp: string;
        level: string;
        event_type: string;
        details: { [key: string]: any } | null;
    };

    type EventStats = {
        total_events: number;
        max_capacity: number;
        levels: { [key: string]: number };
        event_types: { [key: string]: number };
        oldest_event: string | null;
        newest_event: string | null;
    };

    type FileStatus = 'Discovered' | 'Ready' | 'InQueue' | 'Copying' | 'Completed' | 'CompletedDeleteFailed' | 'Failed' | 'Removed' | 'Growing' | 'ReadyToStartGrowing' | 'GrowingCopy' | 'WaitingForSpace' | 'SpaceError' | 'WaitingForNetwork' | 'PausedInQueue' | 'PausedCopying' | 'PausedGrowingCopy';

    type RetryInfo = {
        scheduled_at: string;
        retry_at: string;
        reason: string;
        retry_type: string;
    };

    type TrackedFile = {
        id: string;
        file_path: string;
        status: FileStatus;
        file_size: number;
        last_write_time: string | null;
        copy_progress: number;
        error_message: string | null;
        retry_count: number;
        discovered_at: string;
        creation_time: string | null;
        started_copying_at: string | null;
        completed_at: string | null;
        failed_at: string | null;
        space_error_at: string | null;
        destination_path: string | null;
        growth_rate_mbps: number;
        bytes_copied: number;
        copy_speed_mbps: number;
        last_growth_check: string | null;
        previous_file_size: number;
        first_seen_size: number;
        growth_stable_since: string | null;
        retry_info: RetryInfo | null;
        isDiscovered?: boolean;
        buffer_percent?: number;
    };

    type SortBy = 'activity' | 'discovered' | 'started' | 'completed' | 'filename' | 'size';

    type ActiveFilter = 'all' | 'active' | 'growing' | 'completed' | 'failed';

    type ErrorSeverity = 'info' | 'warning' | 'critical';

    type ChannelError = {
        id: number;
        channel_name: string;
        error_message: string;
        error_code: any;
        timestamp: string;
        severity: ErrorSeverity;
    };

    type ChannelStatus = {
        name: string;
        is_recording: boolean;
        has_signal: boolean;
        has_errors: boolean;
        last_errors: ChannelError[];
        frames: number;
        hours: number;
        minutes: number;
        seconds: number;
        last_update: string;
        last_error?: ChannelError;
    };

    type RecordingTime = {
        hours: number;
        minutes: number;
        seconds: number;
        frames: number;
    };

    type ChunkInfo = {
        has_more_forward: boolean;
        has_more_backward: boolean;
        next_forward_offset: number;
        next_backward_offset: number;
        total_lines: number;
    };

    type LogViewerStore = {
        showLogViewerModal: boolean;
        logFiles: LogFile[];
        loadingLogFiles: boolean;
        logFilesError: string | null;
        selectedLogFile: LogFile | null;
        logContent: string | null;
        loadingLogContent: boolean;
        logChunks: string[];
        currentChunkInfo: ChunkInfo | null;
        loadingChunk: boolean;
        chunkError: string | null;
        viewMode: 'full' | 'chunked';
        init: () => void;
        openLogViewerModal: () => Promise<void>;
        closeLogViewerModal: () => void;
        loadLogFiles: () => Promise<void>;
        loadLogFile: (logFile: LogFile) => Promise<void>;
        loadFullLogContent: (logFile: LogFile) => Promise<void>;
        loadLogChunk: (filename: string, start?: number, direction?: 'forward' | 'backward', limit?: number) => Promise<void>;
        loadMoreForward: () => Promise<void>;
        loadMoreBackward: () => Promise<void>;
        downloadLogFile: (filename: string) => Promise<void>;
    };

    type SettingsData = {
        source_directory: string;
        destination_directory: string;
        output_folder_template_enabled: boolean;
        output_folder_rules: string;
        output_folder_default_category: string;
        output_folder_date_format: string;
        file_stable_time_seconds: number;
        polling_interval_seconds: number;
        use_temporary_file: boolean;
        max_retry_attempts: number;
        retry_delay_seconds: number;
        global_retry_delay_seconds: number;
        copy_progress_update_interval: number;
        file_operation_timeout_seconds: number;
        chunk_size_kb: number;
        log_level: string;
        log_file_path: string;
        log_retention_days: number;
        storage_check_interval_seconds: number;
        source_warning_threshold_gb: number;
        source_critical_threshold_gb: number;
        destination_warning_threshold_gb: number;
        destination_critical_threshold_gb: number;
        storage_test_file_prefix: string;
        enable_pre_copy_space_check: boolean;
        copy_safety_margin_gb: number;
        space_retry_delay_seconds: number;
        max_space_retries: number;
        minimum_free_space_after_copy_gb: number;
        space_error_cooldown_minutes: number;
        keep_files_hours: number;
        growing_file_min_size_mb: number;
        growing_file_safety_margin_mb: number;
        growing_file_poll_interval_seconds: number;
        growing_file_growth_timeout_seconds: number;
        growing_file_chunk_size_kb: number;
        growing_copy_pause_ms: number;
        enable_secure_resume: boolean;
        max_concurrent_copies: number;
        enable_auto_mount: boolean;
        network_share_url: string;
        windows_drive_letter: string;
        macos_mount_point: string;
        justin_api_base_url: string;
        justin_fast_poll_interval_seconds: number;
        justin_slow_poll_interval_seconds: number;
        justin_api_timeout_seconds: number;
        tally_light_api_url: string;
        tally_light_blink_interval_seconds: number;
        tally_light_api_timeout_seconds: number;
    };

    type SettingsStore = {
        showSettingsModal: boolean;
        settingsData: SettingsData | null;
        settingsLoading: boolean;
        settingsError: string | null;
        reloadingConfig: boolean;
        restartingApp: boolean;
        restartCountdown: number | null;
        scannerToggling: boolean;
        actionMessage: string | null;
        actionSuccess: boolean;
        init: () => void;
        openSettingsModal: () => Promise<void>;
        closeSettingsModal: () => void;
        loadSettings: () => Promise<void>;
        showErrorMessage: (message: string) => void;
        reloadConfig: () => Promise<void>;
        restartApplication: () => Promise<void>;
        toggleScanner: () => Promise<void>;
    };

    type StorageStatus = 'OK' | 'WARNING' | 'ERROR' | 'CRITICAL';

    type MountStatus = 'ATTEMPTING' | 'SUCCESS' | 'FAILED' | 'NOT_CONFIGURED';

    type StorageInfo = {
        path: string;
        is_accessible: boolean;
        has_write_access: boolean;
        free_space_gb: number;
        total_space_gb: number;
        used_space_gb: number;
        status: StorageStatus;
        warning_threshold_gb: number;
        critical_threshold_gb: number;
        last_checked: string;
        error_message: string | null;
    };

    type MountStatusInfo = {
        status: MountStatus;
        shareUrl: string | null;
        mountPath: string | null;
        targetPath: string;
        errorMessage: string | null;
        timestamp: Date;
    };

    type StorageUpdateData = {
        storage_type: 'source' | 'destination';
        storage_info: StorageInfo;
    };

    type MountStatusUpdateData = {
        storage_type: 'source' | 'destination';
        mount_status: MountStatus;
        share_url: string | null;
        mount_path: string | null;
        target_path: string;
        error_message: string | null;
        timestamp: string;
    };

    type StorageStore = {
        source: StorageInfo | null;
        destination: StorageInfo | null;
        overall_status: StorageStatus | 'Unknown';
        mountStatus: { source: MountStatusInfo | null, destination: MountStatusInfo | null };
        isLoading: boolean;
        lastUpdated: Date | null;
        updateSource: (data: StorageInfo) => void;
        updateDestination: (data: StorageInfo) => void;
        updateOverallStatus: () => void;
        handleStorageUpdate: (data: StorageUpdateData) => void;
        handleMountStatus: (data: MountStatusUpdateData) => void;
        sourceStatus: StorageStatus | 'Unknown';
        sourceStatusColor: string;
        sourceStatusTextColor: string;
        sourceUsagePercentage: number;
        sourceFreeSpaceFormatted: string;
        sourceTotalSpaceFormatted: string;
        destinationStatus: StorageStatus | 'Unknown';
        destinationStatusColor: string;
        destinationStatusTextColor: string;
        destinationUsagePercentage: number;
        destinationFreeSpaceFormatted: string;
        destinationTotalSpaceFormatted: string;
        sourceAccessible: boolean;
        sourceWritable: boolean;
        destinationAccessible: boolean;
        destinationWritable: boolean;
        sourceMountStatus: MountStatus | null;
        destinationMountStatus: MountStatus | null;
        sourceMountStatusColor: string;
        destinationMountStatusColor: string;
        destinationMountMessage: string | null;
    };

    type ScannerStatus = {
        scanning: boolean;
        paused: boolean;
    };

    type UIStore = {
        showSettingsModal: boolean;
        showLogViewerModal: boolean;
        scanner: ScannerStatus;
        init: () => void;
        updateScannerStatus: (scannerData: Partial<ScannerStatus>) => void;
    };

    type FileStore = {
        MAX_FILES: number;
        items: Map<string, TrackedFile>;
        sortBy: SortBy;
        activeFilter: ActiveFilter;
        statistics: {
            totalFiles: number;
            activeFiles: number;
            completedFiles: number;
            failedFiles: number;
            growingFiles: number;
        };
        setFilter: (filterName: ActiveFilter) => void;
        addFile: (file: TrackedFile) => void;
        updateFile: (fileId: string, partialFile: Partial<TrackedFile>) => void;
        addDiscoveredFile: (discoveredFile: Partial<TrackedFile>) => void;
        setInitialFiles: (files: TrackedFile[]) => void;
        setSortBy: (sortMethod: SortBy) => void;
        updateStatistics: (stats: Partial<FileStore['statistics']>) => void;
        updateStatisticsFromFiles: () => void;
        filteredFiles: TrackedFile[];
        allFiles: TrackedFile[];
        activeFiles: TrackedFile[];
        completedFiles: TrackedFile[];
        growingFiles: TrackedFile[];
        failedFiles: TrackedFile[];
        sortFiles: (files: TrackedFile[]) => TrackedFile[];
    };

    type ConnectionStore = {
        socket: WebSocket | null;
        status: ConnectionStatus;
        text: string;
        lastUpdate: string;
        reconnectAttempts: number;
        maxReconnectAttempts: number;
        reconnectDelay: number;
        reconnectTimeoutId: number | null;
        initDashboard: () => Promise<void>;
        connect: () => void;
        setupSocketHandlers: () => void;
        handleDisconnection: () => void;
        scheduleReconnect: () => void;
        cancelReconnect: () => void;
        updateStatus: (status: ConnectionStatus, text: string) => void;
        updateLastUpdate: () => void;
        onConnected: () => void;
        fetchInitialState: () => Promise<void>;
        statusColor: string;
    };

    type IngestStore = {
        channels: Map<string, ChannelStatus>;
        lastUpdate: string | null;
        isConnected: boolean;
        statistics: {
            totalChannels: number;
            recordingChannels: number;
            errorChannels: number;
            signalLostChannels: number;
        };
        errors: ChannelError[];
        MAX_ERRORS: number;
        isClearing: boolean;
        isStarting: boolean;
        isStopping: boolean;
        recordingTimer: {
            isRunning: boolean;
            startTime: number | null;
            currentTime: RecordingTime | null;
            intervalId: number | null;
            displayTime: string;
        };
        init: () => void;
        loadInitialData: () => Promise<void>;
        updateChannels: (channelsData: { [key: string]: Partial<ChannelStatus> }) => void;
        updateChannel: (channelName: string, channelData: Partial<ChannelStatus>) => void;
        addChannelError: (channelName: string, errorMessage: string, errorCode: any) => void;
        getErrorSeverity: (errorCode: any) => ErrorSeverity;
        updateStatistics: () => void;
        initRecordingTimer: () => void;
        updateRecordingTimer: () => void;
        startRecordingTimer: (baseChannel: ChannelStatus) => void;
        stopRecordingTimer: () => void;
        syncRecordingTimer: (baseChannel: ChannelStatus) => void;
        updateTimerDisplay: () => void;
        getChannelsArray: () => ChannelStatus[];
        getChannelsSorted: () => ChannelStatus[];
        getRecordingStatus: () => 'none' | 'some' | 'all';
        getRecentErrors: () => ChannelError[];
        clearErrors: () => void;
        clearAllErrors: () => Promise<void>;
        startAllChannels: () => Promise<void>;
        stopAllChannels: () => Promise<void>;
        getChannel: (channelName: string) => ChannelStatus | undefined;
        formatTimecode: (hours: number, minutes: number, seconds: number, frames: number) => string;
        formatDuration: (hours: number, minutes: number, seconds: number, frames: number) => string;
        setConnected: (connected: boolean) => void;
        cleanup: () => void;
    };
}

// Export an empty object to make this a module
export {};
