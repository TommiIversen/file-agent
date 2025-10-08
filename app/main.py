from fastapi import FastAPI, Request
import uvicorn
from contextlib import asynccontextmanager
from .routers import api, views
from .config import Settings
from .logging_config import setup_logging, get_app_logger

# Load settings
settings = Settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    setup_logging(settings)
    logger = get_app_logger()
    logger.info("File Transfer Agent starting up...")
    logger.info(f"Source directory: {settings.source_directory}")
    logger.info(f"Destination directory: {settings.destination_directory}")
    
    yield
    
    # Shutdown
    logger.info("File Transfer Agent shutting down...")

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
app.include_router(views.router)
app.include_router(api.router, prefix="/api", tags=["api"])

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")