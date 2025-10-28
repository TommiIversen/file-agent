import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from .api import websockets, storage, logfiles, uiactions

from .domains.directory_browsing import api as directory

from .config import Settings
from .dependencies import (
    get_file_scanner,
    get_job_queue_service,
    get_file_copier,
    get_websocket_manager,
    get_storage_monitor,
    get_storage_checker,
)
from .logging_config import setup_logging
from .routers import views

settings = Settings()

# Global reference til background tasks
_background_tasks = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    setup_logging(settings)

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
    logging.info("StateManager klar til brug")

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

    # Start FileScannerService som background task
    file_scanner = get_file_scanner()
    scanner_task = asyncio.create_task(file_scanner.start_scanning())
    _background_tasks.append(scanner_task)
    logging.info("FileScannerService startet som background task")

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
    websocket_manager = get_websocket_manager()  # Initialize singleton
    logging.info("WebSocketManager initialiseret")

    # Initialize scanner status in WebSocketManager with race condition handling
    websocket_manager.initialize_scanner_status(file_scanner)

    # Start StorageMonitorService som background task
    storage_monitor = get_storage_monitor()
    storage_task = asyncio.create_task(storage_monitor.start_monitoring())
    _background_tasks.append(storage_task)
    logging.info("StorageMonitorService startet som background task")

    yield

    # Shutdown
    logging.info("File Transfer Agent shutting down...")

    # Stop alle background tasks gracefully
    await file_scanner.stop_scanning()
    job_queue_service.stop_producer()
    await file_copier.stop_workers()
    await storage_monitor.stop_monitoring()

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

# Mount static files
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
    logging.info(f"Static files mounted at /static from {static_path}")

# Mount logs directory for log file access
logs_path = settings.log_directory
if logs_path.exists():
    app.mount("/logs", StaticFiles(directory=str(logs_path)), name="logs")
    logging.info(f"Log files mounted at /logs from {logs_path}")
else:
    logging.warning(f"Log directory does not exist: {logs_path}")


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
app.include_router(uiactions.router)
app.include_router(websockets.router)
app.include_router(storage.router)
app.include_router(logfiles.router)
app.include_router(directory.directory_router)
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
