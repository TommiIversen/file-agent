
// Declare Alpine globally
declare const Alpine: any;

// Top-level declarations for new global types
interface AppConfig {
    name: string;
    version: string;
    debug: boolean;
    websocket: {
        autoConnect: boolean;
        reconnectOnError: boolean;
        heartbeatInterval: number;
    };
    ui: {
        defaultSortBy: string;
        refreshInterval: number;
        animationDuration: number;
    };
}

// FileTransferApp is a class defined in app.js
declare class FileTransferApp {
    constructor();
    initialized: boolean;
    stores: {
        connection: ConnectionStore | null;
        files: FileStore | null;
        storage: StorageStore | null;
        ui: UIStore | null;
    } | null;
    services: {
        messageHandler: MessageHandler | null;
        uiHelpers: typeof UIHelpers | null;
    } | null;
    init(): Promise<void>;
    onDocumentReady(): Promise<void>;
    setupAlpine(): void;
    onAlpineInit(): Promise<void>;
    initializeStores(): void;
    initializeServices(): void;
    startApplication(): Promise<void>;
    startWebSocketConnection(): Promise<void>;
    setupPeriodicTasks(): void;
    heartbeat(): void;
    getStoreHealth(): {
        connection: boolean;
        files: boolean;
        storage: boolean;
        filesCount: number;
        connectionStatus: ConnectionStatus | 'unknown';
    };
    setupEventListeners(): void;
    handleInitializationError(error: Error): void;
    handleGlobalError(error: Error | any): void;
    dispatchAppEvent(eventName: string, detail?: object): void;
    getStatus(): {
        initialized: boolean;
        config: AppConfig;
        stores: ReturnType<FileTransferApp['getStoreHealth']>;
        services: string[];
        timestamp: string;
    };
}

interface ConnectionStore {
    socket: WebSocket | null;
    status: ConnectionStatus;
    text: string;
    lastUpdate: string;
    reconnectAttempts: number;
    maxReconnectAttempts: number;
    reconnectDelay: number;
    reconnectTimeoutId: number | null;
    initDashboard(): Promise<void>;
    connect(): void;
    setupSocketHandlers(): void;
    handleDisconnection(): void;
    scheduleReconnect(): void;
    cancelReconnect(): void;
    updateStatus(status: ConnectionStatus, text: string): void;
    updateLastUpdate(): void;
    onConnected(): void;
    fetchInitialState(): Promise<void>;
    readonly statusColor: string;
}

interface FileStore {
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
    setFilter(filterName: ActiveFilter): void;
    addFile(file: TrackedFile): void;
    updateFile(fileId: string, partialFile: Partial<TrackedFile>): void;
    addDiscoveredFile(discoveredFile: Partial<TrackedFile>): void;
    setInitialFiles(files: TrackedFile[]): void;
    setSortBy(sortMethod: SortBy): void;
    updateStatistics(stats: Partial<FileStore['statistics']>): void;
    updateStatisticsFromFiles(): void;
    readonly filteredFiles: TrackedFile[];
    readonly allFiles: TrackedFile[];
    readonly activeFiles: TrackedFile[];
    readonly completedFiles: TrackedFile[];
    readonly growingFiles: TrackedFile[];
    readonly failedFiles: TrackedFile[];
    sortFiles(files: TrackedFile[]): TrackedFile[];
}

interface StorageStore {
    source: StorageInfo | null;
    destination: StorageInfo | null;
    overall_status: StorageStatus | null;
    mountStatus: {
        source: MountStatus | null;
        destination: MountStatus | null;
    };
    isLoading: boolean;
    lastUpdated: Date | null;
    updateOverallStatus(): void;
    updateSource(data: StorageInfo): void;
    updateDestination(data: StorageInfo): void;
    handleStorageUpdate(data: StorageUpdateData): void;
    handleMountStatus(data: MountStatusUpdateData): void;
    readonly sourceStatus: string;
    readonly sourceStatusColor: string;
    readonly sourceStatusTextColor: string;
    readonly sourceUsagePercentage: number;
    readonly sourceFreeSpaceFormatted: string;
    readonly sourceTotalSpaceFormatted: string;
    readonly destinationStatus: string;
    readonly destinationStatusColor: string;
    readonly destinationStatusTextColor: string;
    readonly destinationUsagePercentage: number;
    readonly destinationFreeSpaceFormatted: string;
    readonly destinationTotalSpaceFormatted: string;
    readonly sourceAccessible: boolean;
    readonly sourceWritable: boolean;
    readonly destinationAccessible: boolean;
    readonly destinationWritable: boolean;
    readonly sourceMountStatus: string | null;
    readonly destinationMountStatus: string | null;
    readonly sourceMountStatusColor: string;
    readonly destinationMountStatusColor: string;
    readonly destinationMountMessage: string | null;
}

interface UIStore {
    showSettingsModal: boolean;
    showLogViewerModal: boolean;
    scanner: ScannerStatus;
    init(): void;
    updateScannerStatus(scannerData: Partial<ScannerStatus>): void;
}

interface MessageHandler {
    fileStore: FileStore | null;
    storageStore: StorageStore | null;
    connectionStore: ConnectionStore | null;
    ingestStore: IngestStore | null;
    messageQueue: any[];
    processQueue(): void;
    handleMessage(message: any): void;
    handleInitialState(data: {files: TrackedFile[], statistics: FileStore['statistics'], storage: { source: StorageInfo, destination: StorageInfo, overall_status: StorageStatus }, scanner: ScannerStatus}): void;
    handleFileUpdate(data: {file: TrackedFile}): void;
    handleFileDiscovered(data: {file_path: string, file_size: number, file_size_mb: number, status: FileStatus, last_write_time: string, timestamp: string}): void;
    handleFileProgressUpdate(data: {file_id: string, progress_percent: number, bytes_copied: number, total_bytes: number, copy_speed_mbps: number, is_final: boolean}): void;
    handleFileCopyCompleted(data: {file_path: string, file_id: string, bytes_copied: number, destination_path: string, is_growing_file: boolean, source_size: number, dest_size: number}): void;
    handleStatisticsUpdate(data: {statistics: FileStore['statistics']}): void;
    handleStorageUpdate(data: StorageUpdateData): void;
    handleMountStatus(data: MountStatusUpdateData): void;
    handleScannerStatus(data: ScannerStatus): void;
    handleSystemStatus(data: {overall_health: string, services: any}): void;
    handleIngestStatusUpdate(data: {channels: {[key: string]: ChannelStatus}}): void;
    handleChannelError(data: ChannelError): void;
}

declare class UIHelpers {
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

type ConnectionStatus = 'connected' | 'disconnected' | 'connecting' | 'error';

type SortBy = 'activity' | 'discovered' | 'started' | 'completed' | 'filename' | 'size';
type ActiveFilter = 'active' | 'completed' | 'growing' | 'failed' | 'all';

interface IngestStore {
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
    init(): void;
    loadInitialData(): Promise<void>;
    updateChannels(channelsData: { [key: string]: Partial<ChannelStatus> }): void;
    updateChannel(channelName: string, channelData: Partial<ChannelStatus>): void;
    addChannelError(channelName: string, errorMessage: string, errorCode: any): void;
    getErrorSeverity(errorCode: any): ErrorSeverity;
    updateStatistics(): void;
    initRecordingTimer(): void;
    updateRecordingTimer(): void;
    startRecordingTimer(baseChannel: ChannelStatus): void;
    stopRecordingTimer(): void;
    syncRecordingTimer(baseChannel: ChannelStatus): void;
    updateTimerDisplay(): void;
    getChannelsArray(): ChannelStatus[];
    getChannelsSorted(): ChannelStatus[];
    getRecordingStatus(): 'none' | 'some' | 'all' | 'blink';
    getRecentErrors(): ChannelError[];
    clearErrors(): void;
    clearAllErrors(): Promise<void>;
    startAllChannels(): Promise<void>;
    stopAllChannels(): Promise<void>;
    getChannel(channelName: string): ChannelStatus | undefined;
    formatTimecode(hours: number, minutes: number, seconds: number, frames: number): string;
    formatDuration(hours: number, minutes: number, seconds: number, frames: number): string;
    setConnected(connected: boolean): void;
    cleanup(): void;
}

interface TrackedFile {
    id: string;
    file_path: string;
    file_size: number;
    file_size_mb: number;
    status: FileStatus;
    last_write_time: string;
    discovered_at: string;
    copy_progress: number;
    bytes_copied: number;
    error_message: string | null;
    retry_count: number;
    creation_time: string | null;
    started_copying_at: string | null;
    completed_at: string | null;
    failed_at: string | null;
    space_error_at: string | null;
    destination_path: string | null;
    growth_rate_mbps: number;
    copy_speed_mbps: number;
    last_growth_check: string | null;
    previous_file_size: number;
    first_seen_size: number;
    growth_stable_since: string | null;
    retry_info: any | null;
    isDiscovered: boolean;
    buffer_percent?: number;
}

type FileStatus = 'Discovered' | 'Growing' | 'Ready' | 'ReadyToStartGrowing' | 'InQueue' | 'WaitingForSpace' | 'WaitingForNetwork' | 'Copying' | 'GrowingCopy' | 'PausedInQueue' | 'PausedCopying' | 'PausedGrowingCopy' | 'Completed' | 'CompletedDeleteFailed' | 'Failed' | 'SpaceError' | 'Removed';

interface StorageInfo {
    path: string;
    free_space_mb: number;
    total_space_mb: number;
    status: StorageStatus;
    total_space_gb: number;
    free_space_gb: number;
    is_accessible: boolean;
    has_write_access: boolean;
}

type StorageStatus = 'OK' | 'WARNING' | 'ERROR' | 'Unknown' | 'CRITICAL';

interface ScannerStatus {
    scanning: boolean;
    paused: boolean;
    // Add other properties as needed
}

interface StorageUpdateData {
    storage_type: 'source' | 'destination';
    storage_info: StorageInfo;
}

interface MountStatusUpdateData {
    storage_type: 'source' | 'destination';
    mount_status: 'mounted' | 'unmounted' | 'error' | 'SUCCESS' | 'ATTEMPTING' | 'FAILED' | 'NOT_CONFIGURED';
    share_url: string;
    mount_path: string;
    target_path: string;
    error_message: string;
    timestamp: string;
}

interface MountStatus {
    status: 'mounted' | 'unmounted' | 'error' | 'SUCCESS' | 'ATTEMPTING' | 'FAILED' | 'NOT_CONFIGURED';
    shareUrl: string;
    mountPath: string;
    targetPath: string;
    errorMessage: string;
    timestamp: Date;
}

interface ChannelStatus {
    name: string;
    is_recording: boolean;
    has_signal: boolean;
    has_errors: boolean;
    last_errors: any[];
    frames: number;
    hours: number;
    minutes: number;
    seconds: number;
    last_update: string;
    last_error?: ChannelError;
}

interface ChannelError {
    id: number;
    channel_name: string;
    error_message: string;
    error_code: any;
    timestamp: string;
    severity: ErrorSeverity;
}

type RecordingTime = {
    hours: number;
    minutes: number;
    seconds: number;
    frames: number;
};

type ErrorSeverity = 'info' | 'warning' | 'critical';

// New types for DirectoryBrowserStore
type ScanType = 'source' | 'destination';
type SortField = 'name' | 'size' | 'created' | 'modified' | 'type';
type SortDirection = 'asc' | 'desc';
type ViewMode = 'tree' | 'flat';

interface DirectoryItem {
    name: string;
    path: string;
    is_directory: boolean;
    is_hidden: boolean;
    size_bytes?: number;
    created_time?: string;
    modified_time?: string;
    children?: DirectoryItem[];
    depth_level?: number;
}

interface DirectoryScanResult {
    path: string;
    is_accessible: boolean;
    items?: DirectoryItem[];
    tree?: DirectoryItem[];
    total_items?: number;
    total_files?: number;
    total_directories?: number;
    scan_duration_seconds?: number;
    error_message?: string | null;
}

interface DirectoryBrowserStore {
    isOpen: boolean;
    currentPath: string;
    scanType: ScanType | '';
    modalTitle: string;
    isLoading: boolean;
    isAccessible: boolean;
    items: DirectoryItem[];
    treeStructure: DirectoryItem[];
    totalItems: number;
    totalFiles: number;
    totalDirectories: number;
    scanDuration: number;
    errorMessage: string | null;
    sortBy: SortField;
    sortDirection: SortDirection;
    showHidden: boolean;
    recursive: boolean;
    maxDepth: number;
    viewMode: ViewMode;
    expandedDirectories: Set<string>;
    defaultExpanded: boolean;
    openSourceBrowser(): void;
    openDestinationBrowser(): void;
    closeModal(): void;
    resetState(): void;
    scanDirectory(): Promise<void>;
    readonly displayItems: DirectoryItem[];
    _getFlattenedTreeItems(treeItems: DirectoryItem[], depth?: number): DirectoryItem[];
    _getFlatViewItems(items: DirectoryItem[]): DirectoryItem[];
    getTreeIndentation(item: DirectoryItem): {paddingLeft: string};
    getTreeIcon(item: DirectoryItem): string | null;
    setSortBy(field: SortField): void;
    toggleHidden(): void;
    toggleRecursive(): void;
    setMaxDepth(depth: string | number): void;
    toggleViewMode(): void;
    toggleDirectory(directoryPath: string): void;
    isDirectoryExpanded(directoryPath: string): boolean;
    expandAllDirectories(): void;
    collapseAllDirectories(): void;
    formatFileSize(bytes: number | null | undefined): string;
    formatDateTime(dateString: string | null | undefined): string;
    getFileIcon(item: DirectoryItem): string;
    readonly statusSummary: {text: string, color: string, icon: string};
}

// New types for EventsViewerStore
interface LogEvent {
    timestamp: string;
    level: 'info' | 'warning' | 'error';
    event_type: string;
    details?: { [key: string]: any };
}

interface EventStats {
    total_events: number;
    max_capacity: number;
    levels: { [key: string]: number };
    event_types: { [key: string]: number };
    oldest_event: string | null;
    newest_event: string | null;
}

interface EventsViewerStore {
    isOpen: boolean;
    isLoading: boolean;
    error: string | null;
    events: LogEvent[];
    filteredEvents: LogEvent[];
    levelFilter: 'all' | 'info' | 'warning' | 'error';
    eventTypeFilter: string;
    availableEventTypes: string[];
    currentPage: number;
    eventsPerPage: number;
    totalEvents: number;
    stats: EventStats;
    autoRefresh: boolean;
    refreshInterval: any;
    openModal(): void;
    closeModal(): void;
    loadEvents(): Promise<void>;
    loadStats(): Promise<void>;
    updateAvailableEventTypes(): void;
    applyFilters(): void;
    setLevelFilter(level: 'all' | 'info' | 'warning' | 'error'): void;
    setEventTypeFilter(eventType: string): void;
    readonly paginatedEvents: LogEvent[];
    readonly totalPages: number;
    goToPage(page: number): void;
    nextPage(): void;
    previousPage(): void;
    refresh(): void;
    getLevelBadgeColor(level: string): string;
    getEventTypeIcon(eventType: string): string;
    formatTimestamp(timestamp: string): string;
    formatRelativeTime(timestamp: string): string;
    downloadEvents(): void;
    getFormattedDetails(details: { [key: string]: any } | null): string | null;
}

// New types for LogViewerStore
interface LogFile {
    filename: string;
    size_bytes: number;
    size_mb: number;
    last_modified: string;
    lines?: number;
}

interface ChunkInfo {
    has_more_forward: boolean;
    has_more_backward: boolean;
    next_forward_offset: number;
    next_backward_offset: number;
    total_lines: number;
}

interface LogViewerStore {
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
    initialLoadComplete: boolean;
    init(): void;
    openLogViewerModal(): Promise<void>;
    closeLogViewerModal(): void;
    loadLogFiles(): Promise<void>;
    loadLogFile(logFile: LogFile): Promise<void>;
    loadFullLogContent(logFile: LogFile): Promise<void>;
    loadLogChunk(filename: string, start?: number, direction?: 'forward' | 'backward', limit?: number): Promise<void>;
    loadMoreForward(): Promise<void>;
    loadMoreBackward(): Promise<void>;
    downloadLogFile(filename: string): Promise<void>;
}

// New types for SettingsStore
interface SettingsData {
    general_settings?: any;
    scanner_settings?: any;
    storage_settings?: any;
    ingest_settings?: any;
    system_info?: any;
    // Add more specific properties as they become known
}

interface SettingsStore {
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
    init(): void;
    openSettingsModal(): Promise<void>;
    closeSettingsModal(): void;
    loadSettings(): Promise<void>;
    showErrorMessage(message: string): void;
    reloadConfig(): Promise<void>;
    restartApplication(): Promise<void>;
    toggleScanner(): Promise<void>;
}

interface TallySwitchStore {
    isOnline: boolean | null;
    switchType: string;
    ipAddress: string;
    lastChecked: string | null;
    errorMessage: string | null;
    isMonitoring: boolean;
    init(): void;
    updateStatus(statusData: {
        is_online: boolean;
        switch_type?: string;
        ip_address?: string;
        last_checked?: string;
        error_message?: string;
        is_monitoring?: boolean;
    }): void;
    loadInitialData(initialData: { tally_switch?: any }): void;
    getStatusColor(): string;
    getStatusTooltip(): string;
    getIndicatorText(): string;
}

interface InitialStateData {
    files: any[];
    statistics: any;
    storage: any;
    scanner: any;
    tally_switch?: {
        is_online: boolean;
        switch_type?: string;
        ip_address?: string;
        last_checked?: string;
        error_message?: string;
        is_monitoring?: boolean;
    };
}

interface MessageHandler {
    // MessageHandler interface - stores property is optional
}

// Augmentation for existing global types
interface Window {
    Alpine: any; // Alpine.js global object
    fileTransferApp: FileTransferApp;
    messageHandler: MessageHandler;
    UIHelpers: UIHelpers;
}
