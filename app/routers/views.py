from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def hello_page(request: Request):
    """Simple hello world view with template"""
    return templates.TemplateResponse(
        "index.html", 
        {"request": request, "message": "Hello World from Template!"}
    )