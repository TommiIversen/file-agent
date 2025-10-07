from fastapi import FastAPI
from .routers import api, views

# Create FastAPI application
app = FastAPI(
    title="File Transfer Agent",
    description="Automatiseret service til at flytte videofiler fra lokal mappe til NAS",
    version="0.1.0"
)

# Include routers
app.include_router(views.router)  # Views på root level
app.include_router(api.router, prefix="/api", tags=["api"])  # API endpoints under /api