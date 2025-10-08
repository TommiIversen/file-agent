from fastapi import FastAPI
import uvicorn
from .routers import api, views

# Create FastAPI application
app = FastAPI(
    title="File Transfer Agent",
    description="Automatiseret service til at flytte videofiler fra lokal mappe til NAS",
    version="0.1.0"
)

# Include routers
app.include_router(views.router)
app.include_router(api.router, prefix="/api", tags=["api"])


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False, log_level="debug")