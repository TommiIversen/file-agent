import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.domains.presentation.registration import register_presentation_domain

from .domains.presentation import websockets_endpoint

from app.domains.shared.api import config_api, logs_api, storage_api, events_api
from app.domains.file_discovery.api import scanner_api
from app.domains.ingest_monitor.api import router as ingest_monitor_api
from app.domains.audio_recording.api import router as audio_recording_api

from .domains.presentation.api_endpoints import presentation_router
from .domains.directory_browsing import api as directory



from .config import Settings
from .config import BUILD_TIME, APP_VERSION, APP_DIRECTORY
from .dependencies.core import (
    get_event_bus,
    get_event_store,
    get_file_repository,
    get_global_event_logger,
    get_query_bus,
    get_command_bus,
    get_user_settings_service,
    get_settings,
)
from .dependencies.file_processing import (
    get_job_queue_service,
    get_file_copier,
)
from .dependencies.file_discovery import (
    get_file_discovery_slice,
    get_file_scanner,
)
from .dependencies.storage import (
    get_storage_monitor,
    get_storage_checker,
    register_network_coordinator,
)
from .dependencies.presentation import get_websocket_manager
from .dependencies.lifecycle import get_lifecycle_service
from .dependencies.ingest import (
    get_ingest_api_client,
    get_ingest_monitor_worker,
)
from .dependencies.tally import (
    get_tally_light_event_handler,
    get_tally_switch_monitor,
)
from .models import FileStatus
from .core.exceptions import InvalidTransitionError
from .dependencies.core import get_file_state_machine

from app.domains.directory_browsing.registration import register_directory_browsing_handlers
from app.domains.file_discovery.registration import register_file_discovery_handlers # Import the new registration function
from app.domains.file_processing.registration import register_file_processing_domain # Import file processing registration
from app.domains.shared.registration import register_shared_domain # Import shared domain registration
from app.domains.network_mount.registration import register_network_mount_domain # NetworkCoordinator registration
from app.domains.lifecycle.registration import register_lifecycle_domain # Import lifecycle domain registration
from app.domains.tally_light.registration import register_tally_light_domain # Import tally light domain registration
from app.domains.ingest_monitor.registration import register_ingest_monitor_domain # Import ingest monitor domain registration
from app.domains.audio_recording.registration import register_audio_recording_domain

from app.core.global_event_logger import LoggedEvent
from .logging_config import setup_logging
from app.domains.presentation import views

settings = Settings()

# Global reference til background tasks
_background_tasks = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    setup_logging(settings)

    await _init_database()

    event_bus = get_event_bus()
    event_store = get_event_store()
    global_event_logger = get_global_event_logger()

    await _init_event_logging(event_bus, event_store, global_event_logger)
    tally_handler = await _register_domains(event_bus)
    _log_config_info()
    await _startup_cleanup()
    await _start_background_services()
    await _mount_static_files(app)

    yield

    await _shutdown(tally_handler, event_store, global_event_logger)


# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------

async def _init_database() -> None:
    file_repo = get_file_repository()
    await file_repo.init_db()
    logging.info("Database initialized")

    # Initialize user settings service (loads DB → syncs into Settings singleton)
    canonical_settings = get_settings()
    user_settings_service = get_user_settings_service()
    await user_settings_service.init(target=canonical_settings)

    # Also sync to the module-level `settings` so logging/config_info stays correct
    user_settings_service.sync_to_settings(settings)

    logging.info("User settings service initialized")


async def _init_event_logging(
    event_bus, event_store, global_event_logger  # type: ignore[no-untyped-def]
) -> None:
    global_event_logger.set_event_store(event_store)
    await global_event_logger.register_with_event_bus(event_bus)
    logging.info("GlobalEventLogger registered with SQLite persistence")

    startup_event = LoggedEvent(
        timestamp=datetime.now(timezone.utc),
        event_type="ApplicationStarted",
        message="File Transfer Agent started",
        level="INFO",
        context={"hostname": settings.config_file_info["hostname"]},
    )
    await event_store.add_event(startup_event)


async def _register_domains(event_bus) -> object:  # type: ignore[no-untyped-def]
    """Register all CQRS handlers and domain event subscriptions."""
    logging.info("Registrerer CQRS handlers...")
    query_bus = get_query_bus()
    command_bus = get_command_bus()

    register_directory_browsing_handlers(query_bus, command_bus)
    register_file_discovery_handlers(command_bus, query_bus, get_file_discovery_slice())
    register_shared_domain(command_bus, query_bus)
    register_lifecycle_domain(command_bus)

    # NetworkCoordinator FIRST — other domains depend on it
    network_services = await register_network_mount_domain(event_bus)
    register_network_coordinator(network_services["network_coordinator"])

    await register_file_processing_domain(command_bus, event_bus)
    await register_presentation_domain(query_bus, event_bus)

    ingest_monitor_worker = get_ingest_monitor_worker()
    await register_ingest_monitor_domain(command_bus, query_bus, event_bus, ingest_monitor_worker)

    tally_handler = get_tally_light_event_handler()
    tally_monitor = get_tally_switch_monitor()
    await register_tally_light_domain(command_bus, query_bus, event_bus, tally_handler, tally_monitor)

    # Audio recording — AFTER ingest_monitor (depends on filename query)
    from app.dependencies.audio_recording import get_audio_recording_service
    audio_service = get_audio_recording_service()
    user_settings_service = get_user_settings_service()

    async def _get_user_setting(key: str):
        return user_settings_service.get(key)

    await register_audio_recording_domain(
        command_bus, query_bus, event_bus, audio_service,
        get_user_setting=_get_user_setting,
    )

    # Inject recorder if device already configured
    device_name = settings.audio_device_name
    if device_name:
        try:
            from app.domains.audio_recording.recorder.factory import create_recorder
            recorder = create_recorder(device_name)
            audio_service.set_recorder(recorder)
            logging.info("Audio recorder initialized for device: %s", device_name)
        except Exception:
            logging.warning("Could not initialize audio recorder for '%s'", device_name, exc_info=True)
    else:
        logging.info("Audio recording available but no device configured yet")

    logging.info("Handler-registrering fuldført.")
    return tally_handler


def _log_config_info() -> None:
    logging.info("=" * 60)
    logging.info("  FILE TRANSFER AGENT — STARTING UP")
    logging.info("=" * 60)
    logging.info(f"  Version:       {APP_VERSION}")
    logging.info(f"  Build time:    {BUILD_TIME}")
    logging.info(f"  App directory: {APP_DIRECTORY}")
    logging.info(f"  Frozen:        {getattr(sys, 'frozen', False)}")

    config_info = settings.config_file_info
    logging.info(f"Running on hostname: {config_info['hostname']}")
    logging.info("File Transfer Agent starting up...")
    logging.info(f"Source directory: {settings.source_directory}")
    logging.info(f"Destination directory: {settings.destination_directory}")
    logging.info("CQRS arkitektur klar til brug")


async def _startup_cleanup() -> None:
    storage_checker = get_storage_checker()
    try:
        cleaned_count = await storage_checker.cleanup_all_test_files(
            settings.source_directory, settings.destination_directory
        )
        if cleaned_count > 0:
            logging.info(f"Startup cleanup: removed {cleaned_count} old test files")
    except Exception as e:
        logging.warning(f"Startup cleanup failed (non-critical): {e}")


async def _recover_waiting_network_files(job_queue_service) -> None:  # type: ignore[no-untyped-def]
    """
    Re-evaluate files stuck in transient states from a previous run.

    On startup NetworkCoordinator initialises as AVAILABLE but does *not*
    publish a NetworkStatusChanged event, so persisted WaitingForNetwork
    files would never be picked up again.

    Files in COPYING / GROWING_COPY / IN_QUEUE are also orphaned because
    the workers that were processing them no longer exist after a restart.
    These are reset to DISCOVERED so the scanner can re-discover and
    re-queue them.
    """
    file_repo = get_file_repository()
    state_machine = get_file_state_machine()

    # 1. Re-evaluate WaitingForNetwork files (uses existing recovery logic)
    try:
        await job_queue_service.process_waiting_network_files()
        logging.info("Startup recovery: WaitingForNetwork files re-evaluated")
    except Exception as e:
        logging.warning(f"Startup recovery of WaitingForNetwork files failed (non-critical): {e}")

    # 2. Reset orphaned in-progress files (workers died with the old process)
    #    Two-step transition via state machine:
    #    COPYING/GROWING_COPY/IN_QUEUE → WAITING_FOR_NETWORK → DISCOVERED
    orphan_statuses = {
        FileStatus.COPYING,
        FileStatus.GROWING_COPY,
        FileStatus.IN_QUEUE,
    }
    try:
        all_files = await file_repo.get_all()
        orphaned = [f for f in all_files if f.status in orphan_statuses]
        for f in orphaned:
            old_status = f.status
            try:
                await state_machine.transition(
                    file_id=f.id,
                    new_status=FileStatus.WAITING_FOR_NETWORK,
                    error_message="Interrupted by application restart",
                    copy_progress=0.0,
                    bytes_copied=0,
                )
                await state_machine.transition(
                    file_id=f.id,
                    new_status=FileStatus.DISCOVERED,
                )
                logging.info(
                    f"Startup recovery: reset orphaned file {f.file_path} "
                    f"({old_status.value} → Discovered)"
                )
            except (InvalidTransitionError, ValueError) as e:
                logging.warning(
                    f"Startup recovery: could not reset {f.file_path} "
                    f"from {old_status.value}: {e}"
                )
        if orphaned:
            logging.info(f"Startup recovery: reset {len(orphaned)} orphaned in-progress files")
    except Exception as e:
        logging.warning(f"Startup recovery of orphaned files failed (non-critical): {e}")


async def _start_background_services() -> None:
    """Start all long-running background tasks."""
    file_scanner = get_file_scanner()
    _background_tasks.append(asyncio.create_task(file_scanner.start_scanning()))
    logging.info("CQRS FileScannerService startet som background task")

    job_queue_service = get_job_queue_service()
    job_queue_service.initialize_queue()
    logging.info("JobQueueService queue initialized")

    file_copier = get_file_copier()
    _background_tasks.append(asyncio.create_task(file_copier.start_workers()))
    logging.info("FileCopierService workers startet som background task")

    ws_manager = get_websocket_manager()
    ws_manager.start_sender_task()
    logging.info("WebSocketManager initialiseret")

    storage_monitor = get_storage_monitor()
    await storage_monitor.subscribe_to_events()

    # Run the first storage check synchronously so that
    # get_destination_info() is populated before startup recovery re-queues
    # orphaned files (otherwise SpaceChecker sees "unavailable").
    await storage_monitor.start_monitoring()  # spawns loop task, then awaits first _check_all_storage()
    logging.info("StorageMonitor started and first check completed")

    # --- Startup recovery for orphaned WaitingForNetwork files ---
    await _recover_waiting_network_files(job_queue_service)

    lifecycle_service = get_lifecycle_service()
    _background_tasks.append(asyncio.create_task(lifecycle_service.start_pruning_loop()))
    logging.info("LifecycleService startet som background task for periodic file cleanup")

    ingest_monitor_worker = get_ingest_monitor_worker()
    _background_tasks.append(asyncio.create_task(ingest_monitor_worker.start_monitoring()))
    logging.info("IngestMonitorWorker startet som background task for Just In Engine monitoring")

    tally_switch_monitor = get_tally_switch_monitor()
    _background_tasks.append(asyncio.create_task(tally_switch_monitor.start_monitoring()))
    logging.info("TallySwitchMonitorService startet som background task")


async def _mount_static_files(app: FastAPI) -> None:
    static_path = Path(__file__).parent / "domains" / "presentation" / "static"
    if await asyncio.to_thread(static_path.exists):
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
        logging.info(f"Static files mounted at /static from {static_path}")

    logs_path = settings.log_directory
    if await asyncio.to_thread(logs_path.exists):
        app.mount("/logs", StaticFiles(directory=str(logs_path)), name="logs")
        logging.info(f"Log files mounted at /logs from {logs_path}")
    else:
        logging.warning(f"Log directory does not exist: {logs_path}")


# ---------------------------------------------------------------------------
# Shutdown helper
# ---------------------------------------------------------------------------

async def _shutdown(tally_handler, event_store, global_event_logger) -> None:  # type: ignore[no-untyped-def]
    logging.info("File Transfer Agent shutting down...")

    # Stop services gracefully
    get_websocket_manager().stop_sender_task()
    await get_file_scanner().stop_scanning()
    await get_file_copier().stop_workers()
    await get_storage_monitor().stop_monitoring()
    get_lifecycle_service().stop_pruning_loop()

    ingest_monitor_worker = get_ingest_monitor_worker()
    await ingest_monitor_worker.stop_monitoring()
    logging.info("IngestMonitorWorker stopped")

    try:
        await get_ingest_api_client().close()
        logging.info("IngestApiClient HTTP client closed")
    except Exception as e:
        logging.warning(f"Error closing IngestApiClient: {e}")

    if tally_handler is not None and hasattr(tally_handler, 'shutdown'):
        await tally_handler.shutdown()
        logging.info("TallyLight domain shutdown completed")

    # Shutdown audio recording (stop cleanly if active)
    try:
        from app.dependencies.audio_recording import get_audio_recording_service
        audio_service = get_audio_recording_service()
        await audio_service.shutdown()
        logging.info("AudioRecording domain shutdown completed")
    except Exception as e:
        logging.warning(f"Error shutting down audio recording: {e}")

    # Log shutdown event while DB is still clean
    try:
        shutdown_event = LoggedEvent(
            timestamp=datetime.now(timezone.utc),
            event_type="ApplicationStopped",
            message="File Transfer Agent stopped",
            level="INFO",
        )
        await event_store.add_event(shutdown_event)
    except Exception:
        logging.warning("Failed to write shutdown event", exc_info=True)

    global_event_logger.set_event_store(None)

    # Cancel background tasks
    for task in _background_tasks:
        task.cancel()

    if _background_tasks:
        try:
            await asyncio.wait_for(
                asyncio.gather(*_background_tasks, return_exceptions=True),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logging.error("Shutdown timeout after 30s -- forcing exit")

    try:
        file_repo = get_file_repository()
        await file_repo.close()
        logging.info("Database connection closed")
    except Exception as e:
        logging.warning(f"Error closing database: {e}")

    logging.info("Alle background tasks stoppet")


# Create FastAPI application
app = FastAPI(
    title="File Transfer Agent",
    description="Automatiseret service til at flytte videofiler fra lokal mappe til NAS",
    version="0.1.0",
    lifespan=lifespan,
)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Log indkommende request
    logging.info(
        f"Incoming request: {request.method} {request.url.path}",
        extra={
            "operation": "http_request",
            "method": request.method,
            "path": request.url.path,
            "client_ip": request.client.host if request.client else "unknown",
        },
    )

    # Process request
    response = await call_next(request)

    # Log response
    logging.info(
        f"Response: {response.status_code}",
        extra={
            "operation": "http_response",
            "status_code": response.status_code,
            "path": request.url.path,
        },
    )

    return response


# Include routers
app.include_router(config_api.router) # New shared domain config API
app.include_router(logs_api.router) # New shared domain logs API
app.include_router(storage_api.router) # New shared domain storage API
app.include_router(events_api.router) # New shared domain events API
app.include_router(scanner_api.router) # New file discovery scanner API
app.include_router(ingest_monitor_api) # New ingest monitor API
app.include_router(audio_recording_api) # Audio recording API
app.include_router(websockets_endpoint.router)
app.include_router(directory.directory_router)
app.include_router(presentation_router)
app.include_router(views.router)



@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "File Transfer Agent er kørende"}


@app.get("/health")
async def health():
    """Detaljeret health check."""
    return {"status": "healthy", "service": "file-transfer-agent"}


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app", host="0.0.0.0", port=8000, reload=False, log_level="info"
    )
