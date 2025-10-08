"""
FastAPI application for File Transfer Agent.

Central entry point der samler alle komponenter:
- API endpoints
- StateManager 
- FileScannerService
- Background services  
- Logging setup
- Dependency injection
"""

from fastapi import FastAPI, Request
import uvicorn
import asyncio
from contextlib import asynccontextmanager

from .config import Settings
from .logging_config import setup_logging, get_app_logger
from .api import state, websockets
from .routers import views
from .dependencies import get_file_scanner, get_job_queue_service, get_file_copier, get_websocket_manager

# Load settings
settings = Settings()

# Global reference til background tasks
_background_tasks = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    setup_logging(settings)
    logger = get_app_logger()
    logger.info("File Transfer Agent starting up...")
    logger.info(f"Source directory: {settings.source_directory}")
    logger.info(f"Destination directory: {settings.destination_directory}")
    logger.info("StateManager klar til brug")
    
    # Start FileScannerService som background task
    file_scanner = get_file_scanner()
    scanner_task = asyncio.create_task(file_scanner.start_scanning())
    _background_tasks.append(scanner_task)
    logger.info("FileScannerService startet som background task")
    
    # Start JobQueueService producer som background task
    job_queue_service = get_job_queue_service()
    queue_task = asyncio.create_task(job_queue_service.start_producer())
    _background_tasks.append(queue_task)
    logger.info("JobQueueService producer startet som background task")
    
    # Start FileCopyService consumer som background task
    file_copier = get_file_copier()
    copier_task = asyncio.create_task(file_copier.start_consumer())
    _background_tasks.append(copier_task)
    logger.info("FileCopyService consumer startet som background task")
    
    # Initialize WebSocketManager (subscription happens automatically)
    get_websocket_manager()  # Initialize singleton
    logger.info("WebSocketManager initialiseret og subscribed til StateManager")
    
    yield
    
    # Shutdown
    logger.info("File Transfer Agent shutting down...")
    
    # Stop alle background tasks gracefully
    file_scanner.stop_scanning()
    job_queue_service.stop_producer()
    file_copier.stop_consumer()
    
    # Cancel alle background tasks
    for task in _background_tasks:
        task.cancel()
    
    # Vent på at tasks bliver cancelled
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    
    logger.info("Alle background tasks stoppet")

# Create FastAPI application
app = FastAPI(
    title="File Transfer Agent",
    description="Automatiseret service til at flytte videofiler fra lokal mappe til NAS",
    version="0.1.0",
    lifespan=lifespan
)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger = get_app_logger()
    
    # Log indkommende request
    logger.info(
        f"Incoming request: {request.method} {request.url.path}",
        extra={
            "operation": "http_request",
            "method": request.method,
            "path": request.url.path,
            "client_ip": request.client.host if request.client else "unknown"
        }
    )
    
    # Process request
    response = await call_next(request)
    
    # Log response
    logger.info(
        f"Response: {response.status_code}",
        extra={
            "operation": "http_response", 
            "status_code": response.status_code,
            "path": request.url.path
        }
    )
    
    return response

# Include routers
app.include_router(state.router)
app.include_router(websockets.router)
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
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")