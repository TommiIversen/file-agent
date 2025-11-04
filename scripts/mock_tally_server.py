#!/usr/bin/env python3
"""
Mock Tally Light Server

Simulates an IP Power Switch for testing the TallyLight integration.
This server provides /on and /off endpoints that the TallyLightEventHandler
can call during development and testing.

Usage:
    python mock_tally_server.py

The server will run on http://localhost:8001/api/switch
"""

import logging
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Mock Tally Light Server",
    description="Simulates an IP Power Switch for testing",
    version="1.0.0"
)

# Current state
tally_state = {
    "is_on": False,
    "last_change": datetime.now().isoformat(),
    "total_on_requests": 0,
    "total_off_requests": 0
}


@app.post("/api/switch/on")
async def turn_on():
    """Turn the tally light ON."""
    global tally_state
    
    tally_state["is_on"] = True
    tally_state["last_change"] = datetime.now().isoformat()
    tally_state["total_on_requests"] += 1
    
    logger.info(f"🔴 TALLY LIGHT ON (Request #{tally_state['total_on_requests']})")
    
    return JSONResponse({
        "status": "success",
        "action": "on",
        "state": tally_state["is_on"],
        "timestamp": tally_state["last_change"]
    })


@app.post("/api/switch/off")
async def turn_off():
    """Turn the tally light OFF."""
    global tally_state
    
    tally_state["is_on"] = False
    tally_state["last_change"] = datetime.now().isoformat()
    tally_state["total_off_requests"] += 1
    
    logger.info(f"⚫ TALLY LIGHT OFF (Request #{tally_state['total_off_requests']})")
    
    return JSONResponse({
        "status": "success", 
        "action": "off",
        "state": tally_state["is_on"],
        "timestamp": tally_state["last_change"]
    })


@app.get("/api/switch/status")
async def get_status():
    """Get current tally light status."""
    return JSONResponse({
        "state": tally_state,
        "description": "Mock Tally Light - simulates IP Power Switch"
    })


@app.get("/")
async def root():
    """Root endpoint with server info."""
    return {
        "message": "Mock Tally Light Server Running",
        "endpoints": {
            "turn_on": "POST /api/switch/on",
            "turn_off": "POST /api/switch/off", 
            "status": "GET /api/switch/status"
        },
        "current_state": tally_state
    }


if __name__ == "__main__":
    logger.info("Starting Mock Tally Light Server...")
    logger.info("Endpoints:")
    logger.info("  POST http://localhost:8001/api/switch/on  - Turn tally light ON")
    logger.info("  POST http://localhost:8001/api/switch/off - Turn tally light OFF")
    logger.info("  GET  http://localhost:8001/api/switch/status - Get current status")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info"
    )