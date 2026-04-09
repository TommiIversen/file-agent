from pathlib import Path
from time import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

from app.dependencies.core import get_settings

router = APIRouter()
_templates_dir = Path(__file__).parent / "templates"

# Boot-time cache buster — changes every restart so browsers fetch fresh static files.
_cache_buster = str(int(time()))

# Create Environment with cache disabled to avoid LRUCache hash bug
# in Jinja2 3.1.x with Python 3.13+
_env = Environment(
    loader=FileSystemLoader(str(_templates_dir)),
    autoescape=True,
    cache_size=0,
)
_env.globals["v"] = _cache_buster
templates = Jinja2Templates(env=_env)


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"brand_name": get_settings().brand_name},
    )
