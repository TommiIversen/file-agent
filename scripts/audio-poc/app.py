import os
os.environ["SD_ENABLE_ASIO"] = "1"

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from recorder import Recorder, query_asio_devices, get_asio_thread, shutdown_asio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

recorder: Recorder | None = None
_current_files: list[str] = []


# --- Models ---

class StartRequest(BaseModel):
    device: str
    samplerate: int
    channels: int = 14


class StopResponse(BaseModel):
    status: str
    overflow_count: int = 0
    writer_error: str | None = None
    files: list[str] = []


class DeviceInfo(BaseModel):
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: int


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    get_asio_thread()
    logger.info("Recorder API startet")
    yield
    global recorder
    if recorder and recorder.is_recording:
        logger.info("Stopper aktiv optagelse ved shutdown...")
        await recorder.astop()
    shutdown_asio()
    logger.info("ASIO driver frigivet")


app = FastAPI(title="ASIO Recorder", lifespan=lifespan)


# --- API Endpoints ---

@app.get("/api/devices", response_model=list[DeviceInfo])
async def list_devices():
    """List alle tilgængelige ASIO-enheder."""
    at = get_asio_thread()
    devices = await at.asubmit(query_asio_devices)
    return [DeviceInfo(**d) for d in devices]


@app.post("/api/record/start")
async def start_recording(req: StartRequest):
    """Start optagelse med angivet device og samplerate."""
    global recorder
    if recorder and recorder.is_recording:
        raise HTTPException(status_code=409, detail="Optagelse er allerede i gang")

    try:
        recorder = Recorder(
            device=req.device,
            channels=req.channels,
            samplerate=req.samplerate,
        )
        files = await recorder.astart()
        _current_files.clear()
        _current_files.extend(str(f) for f in files)
        return {
            "status": "recording",
            "device": req.device,
            "samplerate": req.samplerate,
            "channels": req.channels,
            "files": list(_current_files),
        }
    except Exception as e:
        recorder = None
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/record/stop", response_model=StopResponse)
async def stop_recording():
    """Stop aktiv optagelse."""
    global recorder
    if not recorder or not recorder.is_recording:
        raise HTTPException(status_code=409, detail="Ingen aktiv optagelse")

    result = await recorder.astop()
    response = StopResponse(
        status=result.get("status", "stopped"),
        overflow_count=result.get("overflow_count", 0),
        writer_error=result.get("writer_error"),
        files=list(_current_files),
    )
    _current_files.clear()
    recorder = None
    return response


@app.get("/api/record/status")
async def recording_status():
    """Hent aktuel optagelsesstatus."""
    if recorder and recorder.is_recording:
        return {
            "recording": True,
            "device": recorder.device_name,
            "samplerate": recorder.samplerate,
            "channels": recorder.channels,
            "overflow_count": recorder._overflow_count,
        }
    return {"recording": False}


# --- UI ---

@app.get("/", response_class=HTMLResponse)
async def ui():
    return Path("static/index.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
