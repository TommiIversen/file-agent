from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

router = APIRouter()
_templates_dir = Path(__file__).parent / "templates"

# Create Environment with cache disabled to avoid LRUCache hash bug
# in Jinja2 3.1.x with Python 3.13+
_env = Environment(
    loader=FileSystemLoader(str(_templates_dir)),
    autoescape=True,
    cache_size=0,
)
templates = Jinja2Templates(env=_env)


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
    )
