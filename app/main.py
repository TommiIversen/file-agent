import asyncio
import logging
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

from .domains.presentation.api_endpoints import presentation_router
from .domains.directory_browsing import api as directory



from .config import Settings
from .dependencies import (
    get_event_bus,
    get_event_store,
    get_file_repository,
    get_global_event_logger,
    get_ingest_api_client,
    get_job_queue_service,
    get_file_copier,
    get_websocket_manager,
    get_storage_monitor,
    get_storage_checker,
    get_query_bus,
    get_command_bus,
    get_file_discovery_slice,
    get_file_scanner,
    get_lifecycle_service,
    get_ingest_monitor_worker,
    get_tally_light_event_handler,
    get_tally_switch_monitor,
    register_network_coordinator,
)

from app.domains.directory_browsing.registration import register_directory_browsing_handlers
from app.domains.file_discovery.registration import register_file_discovery_handlers # Import the new registration function
from app.domains.file_processing.registration import register_file_processing_domain # Import file processing registration
from app.domains.shared.registration import register_shared_domain # Import shared domain registration
from app.domains.network_mount.registration import register_network_mount_domain # NetworkCoordinator registration
from app.domains.lifecycle.registration import register_lifecycle_domain # Import lifecycle domain registration
from app.domains.tally_light.registration import register_tally_light_domain # Import tally light domain registration
from app.domains.ingest_monitor.registration import register_ingest_monitor_domain # Import ingest monitor domain registration

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

    event_bus = get_event_bus()
    event_store = get_event_store()
    global_event_logger = get_global_event_logger()

    await _init_database()
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
    await register_tally_light_domain(command_bus, event_bus, tally_handler)

    logging.info("Handler-registrering fuldført.")
    return tally_handler


def _log_config_info() -> None:
    config_info = settings.config_file_info
    logging.info(f"Configuration loaded from: {config_info['active_config_file']}")
    logging.info(f"Running on hostname: {config_info['hostname']}")
    if len(config_info["all_available_configs"]) > 1:
        logging.info(
            f"Available config files: {', '.join(config_info['all_available_configs'])}"
        )
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


async def _start_background_services() -> None:
    """Start all long-running background tasks."""
    file_scanner = get_file_scanner()
    _background_tasks.append(asyncio.create_task(file_scanner.start_scanning()))
    logging.info("CQRS FileScannerService startet som background task")

    job_queue_service = get_job_queue_service()
    _background_tasks.append(asyncio.create_task(job_queue_service.start_producer()))
    logging.info("JobQueueService producer startet som background task")

    file_copier = get_file_copier()
    _background_tasks.append(asyncio.create_task(file_copier.start_workers()))
    logging.info("FileCopierService workers startet som background task")

    ws_manager = get_websocket_manager()
    ws_manager.start_sender_task()
    logging.info("WebSocketManager initialiseret")

    storage_monitor = get_storage_monitor()
    await storage_monitor.subscribe_to_events()
    _background_tasks.append(asyncio.create_task(storage_monitor.start_monitoring()))

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
    get_job_queue_service().stop_producer()
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
