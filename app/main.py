import asyncio
import logging
from contextlib import asynccontextmanager
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
    get_job_queue_service,
    get_file_copier,
    get_websocket_manager,
    get_storage_monitor,
    get_storage_checker,
    get_query_bus,
    get_command_bus,
    get_file_discovery_slice,  # Import the new slice getter
    get_file_scanner,
    get_lifecycle_service,  # Import lifecycle service
    get_ingest_monitor_worker,  # Import refactored ingest monitor worker
    get_tally_light_event_handler,  # Import tally light handler
    get_tally_switch_monitor  # Import tally switch monitor service
)

from app.domains.directory_browsing.registration import register_directory_browsing_handlers
from app.domains.file_discovery.registration import register_file_discovery_handlers  # Import the new registration function
from app.domains.file_processing.registration import register_file_processing_domain  # Import file processing registration
from app.domains.shared.registration import register_shared_domain  # Import shared domain registration
from app.domains.network_mount.registration import register_network_mount_domain  # 🚀 NetworkCoordinator registration
from app.domains.lifecycle.registration import register_lifecycle_domain  # Import lifecycle domain registration
from app.domains.tally_light.registration import register_tally_light_domain  # Import tally light domain registration
from app.domains.ingest_monitor.registration import register_ingest_monitor_domain  # Import ingest monitor domain registration

from .logging_config import setup_logging
from app.domains.presentation import views

settings = Settings()

# Global reference til background tasks
_background_tasks = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    setup_logging(settings)

    # === START: NYT REGISTRERINGSTRIN ===
    logging.info("Registrerer CQRS handlers...")
    query_bus = get_query_bus()
    command_bus = get_command_bus()
    event_bus = get_event_bus()
    
    # 🔧 Register GlobalEventLogger to capture all domain events for UI visibility
    from app.dependencies import get_global_event_logger
    global_event_logger = get_global_event_logger()
    await global_event_logger.register_with_event_bus(event_bus)
    logging.info("GlobalEventLogger registered for UI event visibility")
    
    # Kald registrerings-funktionerne for hvert domæne
    register_directory_browsing_handlers(query_bus, command_bus)
    register_file_discovery_handlers(command_bus, query_bus, get_file_discovery_slice())  # New registration call
    register_shared_domain(command_bus, query_bus)  # Register shared domain handlers
    register_lifecycle_domain(command_bus)  # Register lifecycle domain handlers
    
    # 🚀 IMPORTANT: Register NetworkCoordinator FIRST before other domains that depend on it!
    network_services = await register_network_mount_domain(event_bus)  # 🚀 NetworkCoordinator registration!
    
    # Store NetworkCoordinator for dependency injection
    from app.dependencies import _singletons
    _singletons["network_coordinator"] = network_services["network_coordinator"]
    
    # Now register domains that depend on NetworkCoordinator
    await register_file_processing_domain(command_bus, event_bus)  # File processing CQRS registration
    await register_presentation_domain(query_bus, event_bus) # <-- OPDATERET KALD
    
    # Register IngestMonitor domain (enables API queries)
    ingest_monitor_worker = get_ingest_monitor_worker()
    register_ingest_monitor_domain(command_bus, query_bus, event_bus, ingest_monitor_worker)
    
    # Register TallyLight domain (depends on IngestMonitor events)
    tally_handler = get_tally_light_event_handler()
    await register_tally_light_domain(command_bus, event_bus, tally_handler)
    
    logging.info("Handler-registrering fuldført.")

    # Log configuration file information
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

    # Cleanup old test files at startup
    storage_checker = get_storage_checker()
    try:
        cleaned_count = await storage_checker.cleanup_all_test_files(
            settings.source_directory, settings.destination_directory
        )
        if cleaned_count > 0:
            logging.info(f"Startup cleanup: removed {cleaned_count} old test files")
    except Exception as e:
        logging.warning(f"Startup cleanup failed (non-critical): {e}")

    # Start CQRS File Scanner Service som background task
    file_scanner = get_file_scanner()
    scanner_task = asyncio.create_task(file_scanner.start_scanning())
    _background_tasks.append(scanner_task)
    logging.info("CQRS FileScannerService startet som background task")

    # Start JobQueueService producer som background task
    job_queue_service = get_job_queue_service()
    queue_task = asyncio.create_task(job_queue_service.start_producer())
    _background_tasks.append(queue_task)
    logging.info("JobQueueService producer startet som background task")

    # Start FileCopierService workers som background task
    file_copier = get_file_copier()
    copier_task = asyncio.create_task(file_copier.start_workers())
    _background_tasks.append(copier_task)
    logging.info("FileCopierService workers startet som background task")

    # Initialize WebSocketManager (subscription happens automatically)
    ws_manager = get_websocket_manager()  # Initialize singleton
    ws_manager.start_sender_task()
    logging.info("WebSocketManager initialiseret")

    # Start StorageMonitorService som background task
    storage_monitor = get_storage_monitor()
    
    # Subscribe StorageMonitor to network events for immediate response
    await storage_monitor.subscribe_to_events()
    
    storage_task = asyncio.create_task(storage_monitor.start_monitoring())
    _background_tasks.append(storage_task)

    # Start LifecycleService som background task for periodic cleanup
    lifecycle_service = get_lifecycle_service()
    lifecycle_task = asyncio.create_task(lifecycle_service.start_pruning_loop())
    _background_tasks.append(lifecycle_task)
    logging.info("LifecycleService startet som background task for periodic file cleanup")

    # Start IngestMonitorWorker som background task for Just In Engine monitoring
    ingest_monitor_worker = get_ingest_monitor_worker()
    ingest_monitor_task = asyncio.create_task(ingest_monitor_worker.start_monitoring())
    _background_tasks.append(ingest_monitor_task)
    logging.info("IngestMonitorWorker startet som background task for Just In Engine monitoring")

    # Start TallySwitchMonitorService som background task for IP switch status monitoring
    tally_switch_monitor = get_tally_switch_monitor()
    tally_switch_task = asyncio.create_task(tally_switch_monitor.start_monitoring())
    _background_tasks.append(tally_switch_task)
    logging.info("TallySwitchMonitorService startet som background task for IP switch connectivity monitoring")
    logging.info("IngestMonitorWorker startet som background task for Just In Engine monitoring")

    # Mount static files
    static_path = Path(__file__).parent / "domains" / "presentation" / "static"
    if await asyncio.to_thread(static_path.exists):
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
        logging.info(f"Static files mounted at /static from {static_path}")

    # Mount logs directory for log file access
    logs_path = settings.log_directory
    if await asyncio.to_thread(logs_path.exists):
        app.mount("/logs", StaticFiles(directory=str(logs_path)), name="logs")
        logging.info(f"Log files mounted at /logs from {logs_path}")
    else:
        logging.warning(f"Log directory does not exist: {logs_path}")

    yield

    # Shutdown
    logging.info("File Transfer Agent shutting down...")

    # Stop alle background tasks gracefully
    get_websocket_manager().stop_sender_task()
    await file_scanner.stop_scanning()
    job_queue_service.stop_producer()
    await file_copier.stop_workers()
    await storage_monitor.stop_monitoring()
    get_lifecycle_service().stop_pruning_loop()  # Stop lifecycle service
    
    # Stop Just In Engine monitoring and tally light services
    ingest_monitor_worker = get_ingest_monitor_worker()
    await ingest_monitor_worker.stop_monitoring()
    logging.info("IngestMonitorWorker stopped")
    
    if 'tally_handler' in locals() and hasattr(tally_handler, 'shutdown'):
        await tally_handler.shutdown()
        logging.info("TallyLight domain shutdown completed")

    # Cancel alle background tasks
    for task in _background_tasks:
        task.cancel()

    # Vent på at tasks bliver cancelled
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)

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
app.include_router(config_api.router)  # New shared domain config API
app.include_router(logs_api.router)  # New shared domain logs API
app.include_router(storage_api.router)  # New shared domain storage API
app.include_router(events_api.router)  # New shared domain events API
app.include_router(scanner_api.router)  # New file discovery scanner API
app.include_router(ingest_monitor_api)  # New ingest monitor API
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
