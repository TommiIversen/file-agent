from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.state_manager import StateManager
from app.dependencies import get_state_manager

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(
    request: Request, state_manager: StateManager = Depends(get_state_manager)
):
    """
    Real-time File Transfer Agent dashboard.

    Serves the main monitoring interface med WebSocket support.
    """
    # Get initial statistics for template context
    try:
        statistics = await state_manager.get_statistics()
        all_files = await state_manager.get_all_files()

        # Separate active and completed files for UI
        active_files = [f for f in all_files if f.status.value != "Completed"]
        completed_files = [f for f in all_files if f.status.value == "Completed"]

    except Exception:
        # Fallback hvis StateManager ikke er klar endnu
        statistics = {
            "total_files": 0,
            "active_files": 0,
            "completed_files": 0,
            "failed_files": 0,
        }
        active_files = []
        completed_files = []

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "statistics": statistics,
            "active_files_count": len(active_files),
            "completed_files_count": len(completed_files),
            "page_title": "File Transfer Agent - Real-time Monitor",
        },
    )
