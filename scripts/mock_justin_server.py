import asyncio
import logging
import time
import random
from contextlib import asynccontextmanager
from typing import Dict, Any, List

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

# --- Konfiguration ---

# Sæt porten til at matche Just In API'et
MOCK_SERVER_PORT = 8080

# Den faste liste af kanaler
CHANNEL_NAMES = [
    "KAM_1", "KAM_2", "KAM_3", "KAM_4",
    "KAM_5", "KAM_6", "KAM_7", "KAM_8"
]

# Hvor længe hver test-tilstand skal vare
STATE_DURATION_SECONDS = 4

# Opsæt simpel logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s (MockServer): %(message)s",
    datefmt="%H:%M:%S",
)

# --- Global Tilstand ---
# Dette er den "database", som vores mock-server læser fra.
# Baggrunds-tasken opdaterer "rec"-feltet her.
GLOBAL_CHANNEL_STATE: Dict[str, Dict[str, Any]] = {}

# Global error state - hvilke kanaler har fejl lige nu
GLOBAL_ERROR_CHANNELS: List[str] = []

# Manual mode state - hvis True, stops auto-cycling
MANUAL_MODE = False
AUTO_CYCLER_TASK = None

# Recording start times - tracks when each channel started recording (for realistic time calculation)
RECORDING_START_TIMES: Dict[str, float] = {}

# --- Pydantic Modeller ---

class ChannelRequest(BaseModel):
    """Matcher den POST-body, vi forventer."""
    channel: str

class ErrorRequest(BaseModel):
    """Request model for /ingest/errors endpoint."""
    channel: str
    clear: int = 0

class StartRecordingRequest(BaseModel):
    """Request model for /ingest/startRecordingWithFilename endpoint."""
    channel: str
    proposed_filename: str = ""
    metadata: Dict[str, Any] = {}

class StopRecordingRequest(BaseModel):
    """Request model for /ingest/stopRecording endpoint."""
    channel: str  
    metadata: Dict[str, Any] = {}

# --- Hjælpefunktioner ---

def _create_mock_response(channel_name: str, rec_status: bool) -> Dict[str, Any]:
    """Genererer den store JSON-respons for en given kanal."""
    
    # Calculate realistic recording time if channel is recording
    hours, minutes, seconds = 0, 0, 0
    if rec_status and channel_name in RECORDING_START_TIMES:
        elapsed_seconds = int(time.time() - RECORDING_START_TIMES[channel_name])
        hours = elapsed_seconds // 3600
        minutes = (elapsed_seconds % 3600) // 60
        seconds = elapsed_seconds % 60
    
    return {
        "rec": rec_status,
        "frames": 11,
        "channel": channel_name,
        "hours": hours,
        "minutes": minutes,
        "seconds": seconds,
        "options": {
            "TOAJustInEngineTimecodeSource": 6,
            "TOAJustInEngineLicenseStatus": True,
            "TOAJustInEngineRecordingMode": 1,
            "TOAJustInEngineAlternativeStartTimecodeFrames": 0,
            "TOAJustInEngineTimecodeOffset": 0,
            "TOAJustInEngineVideoSignalAvailable": True,
            "TOAJustInEngineAlternativeStopTimecodeFrames": 0,
            "TOAJustInEngineRecordingError": False,
            "TOAJustInEngineLiveCutEnabled": False,
            "TOAJustInEngineMetadataWritingOption": 1,
            "TOAJustInEngineStartTimecodeFrames": 0,
            "TOAJustInEngineAlternativeStartTimecodeActive": False,
            "TOAJustInEngineFramerate": 2500,
            "TOAJustInEngineAlternativeStopTimecodeActive": False
        },
        "name": channel_name
    }

def _create_mock_error_response(channel_name: str) -> Dict[str, Any]:
    """Genererer mock error response for en kanal med ALTID 2 fejl."""
    # Note: EPOC har altid forkert år (1994 i stedet for 2025)
    # Dette simulerer det samme problem som det rigtige Just In system
    wrong_year_timestamp = time.time() - (31 * 365.25 * 24 * 60 * 60)  # Cirka 31 år tilbage
    
    # Forskellige fejl typer for varieret simulation
    error_types = [
        {
            "errorCode": -8995,
            "errorDomain": "TOAErrorDomainGeneric",
            "errorUIDescription": "No signal",
            "errorUserInfo": {
                "NSLocalizedDescription": "No signal, please check the incoming video format."
            },
            "errorType": 3
        },
        {
            "errorCode": -8996,
            "errorDomain": "TOAErrorDomainVideo",
            "errorUIDescription": "Video format mismatch",
            "errorUserInfo": {
                "NSLocalizedDescription": "Expected 1080i50, received 720p50."
            },
            "errorType": 2
        },
        {
            "errorCode": -8997,
            "errorDomain": "TOAErrorDomainAudio",
            "errorUIDescription": "Audio dropout detected",
            "errorUserInfo": {
                "NSLocalizedDescription": "Intermittent audio signal on channel 1-2."
            },
            "errorType": 1
        },
        {
            "errorCode": -8998,
            "errorDomain": "TOAErrorDomainStorage",
            "errorUIDescription": "Disk space low",
            "errorUserInfo": {
                "NSLocalizedDescription": "Less than 5% disk space remaining on recording volume."
            },
            "errorType": 2
        },
        {
            "errorCode": -8999,
            "errorDomain": "TOAErrorDomainNetwork",
            "errorUIDescription": "Network timeout",
            "errorUserInfo": {
                "NSLocalizedDescription": "Connection to remote server timed out after 30 seconds."
            },
            "errorType": 1
        }
    ]
    
    # Altid vælg 2 forskellige fejl for hver kanal
    # Vælg baseret på kanal navn for konsistens, men altid 2 fejl
    hash_value = hash(channel_name)
    first_error_index = hash_value % len(error_types)
    second_error_index = (hash_value + 1) % len(error_types)
    
    # Sørg for at vi ikke får samme fejl to gange
    if first_error_index == second_error_index:
        second_error_index = (second_error_index + 1) % len(error_types)
    
    # Opret 2 fejl med forskellige timestamps
    first_error = error_types[first_error_index].copy()
    first_error["date"] = wrong_year_timestamp
    
    second_error = error_types[second_error_index].copy()
    second_error["date"] = wrong_year_timestamp - 60  # 1 minut tidligere
    
    return {
        "channel": channel_name,
        "name": channel_name,
        "errors": [first_error, second_error]  # ALTID 2 fejl
    }

async def _state_cycler_task():
    """
    Baggrunds-task, der cykler både Tally-tilstand og Error-tilstand.
    
    Recording cycle (4 sek hver):
    1. Alle kanaler OFF
    2. Alle kanaler ON  
    3. KAM_8 OFF, resten ON
    
    Error cycle (4 sek hver):
    4. Ingen fejl
    5. 1 fejl på random kanal
    6. 2 fejl på random kanaler
    
    Total cycle: 24 sekunder
    
    Stopper automatisk hvis MANUAL_MODE = True
    """
    global MANUAL_MODE
    logging.info("State Cycler Task startet. Cykler recording + error status hver 4. sekund.")
    
    while not MANUAL_MODE:
        try:
            # --- Tilstand 1: ALLE SLUKKET ---
            if MANUAL_MODE:
                break
            logging.info("--- STATE 1: ALLE KANALER 'rec: false' ---")
            for name in CHANNEL_NAMES:
                GLOBAL_CHANNEL_STATE[name]["rec"] = False
                # Remove start time when stopping
                RECORDING_START_TIMES.pop(name, None)
            await asyncio.sleep(STATE_DURATION_SECONDS)

            # --- Tilstand 2: ALLE TÆNDT ---
            if MANUAL_MODE:
                break
            logging.info("--- STATE 2: ALLE KANALER 'rec: true' ---")
            current_time = time.time()
            for name in CHANNEL_NAMES:
                GLOBAL_CHANNEL_STATE[name]["rec"] = True
                # Set start time when starting
                RECORDING_START_TIMES[name] = current_time
            await asyncio.sleep(STATE_DURATION_SECONDS)

            # --- Tilstand 3: ÉN SLUKKET (fejl-tilstand) ---
            if MANUAL_MODE:
                break
            logging.info("--- STATE 3: KAM_8 'rec: false', RESTEN 'rec: true' ---")
            current_time = time.time()
            for name in CHANNEL_NAMES:
                if name == "KAM_8":
                    GLOBAL_CHANNEL_STATE[name]["rec"] = False
                    # Remove start time when stopping
                    RECORDING_START_TIMES.pop(name, None)
                else:
                    GLOBAL_CHANNEL_STATE[name]["rec"] = True
                    # Set start time if not already recording
                    if name not in RECORDING_START_TIMES:
                        RECORDING_START_TIMES[name] = current_time
            await asyncio.sleep(STATE_DURATION_SECONDS)

            # --- ERROR CYCLES ---
            
            # Error Cycle 1: Ingen fejl
            if MANUAL_MODE:
                break
            logging.info("--- ERROR CYCLE 1: INGEN FEJL ---")
            GLOBAL_ERROR_CHANNELS.clear()
            await asyncio.sleep(STATE_DURATION_SECONDS)

            # Error Cycle 2: 1 fejl på random kanal
            if MANUAL_MODE:
                break
            logging.info("--- ERROR CYCLE 2: 1 FEJL PÅ RANDOM KANAL ---")
            GLOBAL_ERROR_CHANNELS.clear()
            random_channel = random.choice(CHANNEL_NAMES)
            GLOBAL_ERROR_CHANNELS.append(random_channel)
            logging.info(f"Fejl på: {random_channel}")
            await asyncio.sleep(STATE_DURATION_SECONDS)

            # Error Cycle 3: 2 fejl på random kanaler
            if MANUAL_MODE:
                break
            logging.info("--- ERROR CYCLE 3: 2 FEJL PÅ RANDOM KANALER ---")
            GLOBAL_ERROR_CHANNELS.clear()
            random_channels = random.sample(CHANNEL_NAMES, 2)
            GLOBAL_ERROR_CHANNELS.extend(random_channels)
            logging.info(f"Fejl på: {', '.join(random_channels)}")
            await asyncio.sleep(STATE_DURATION_SECONDS)

        except asyncio.CancelledError:
            logging.info("State Cycler Task stoppet.")
            break
        except Exception as e:
            logging.error(f"Fejl i State Cycler Task: {e}")
            await asyncio.sleep(STATE_DURATION_SECONDS)
    
    logging.info("State Cycler Task afsluttet - MANUAL_MODE aktiveret.")


# --- FastAPI App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Håndterer opstart og nedlukning af serveren."""
    global AUTO_CYCLER_TASK
    
    # Opstart: Initialiser den globale tilstand
    logging.info("Mock-server starter... Initialiserer global tilstand.")
    for name in CHANNEL_NAMES:
        # Start med at alt er slukket
        GLOBAL_CHANNEL_STATE[name] = _create_mock_response(name, rec_status=False)
    
    # Start baggrunds-tasken
    AUTO_CYCLER_TASK = asyncio.create_task(_state_cycler_task())
    
    yield # App'en kører
    
    # Nedlukning: Stop baggrunds-tasken
    logging.info("Mock-server lukker ned... Stopper baggrunds-task.")
    if AUTO_CYCLER_TASK:
        AUTO_CYCLER_TASK.cancel()
        try:
            await AUTO_CYCLER_TASK
        except asyncio.CancelledError:
            pass

app = FastAPI(lifespan=lifespan)

# --- API Endpoints ---

@app.get("/ingest/activeChannels")
async def get_active_channels() -> Dict[str, List[str]]:
    """Returnerer den faste liste af kanaler."""
    logging.info(f"Modtog GET /ingest/activeChannels. Returnerer {len(CHANNEL_NAMES)} kanaler.")
    return {"channel-names": CHANNEL_NAMES}

@app.post("/ingest/requestRecordingStatus")
async def get_recording_status(request: ChannelRequest):
    """
    Returnerer den *nuværende* mock-status for en specifik kanal
    fra den globale tilstand med opdateret tid.
    """
    channel_name = request.channel
    
    if channel_name not in GLOBAL_CHANNEL_STATE:
        logging.warning(f"Modtog POST for ukendt kanal: {channel_name}")
        return {"error": "Channel not found"}

    # Hent den nuværende recording status og regenerer response med aktuel tid
    current_rec_status = GLOBAL_CHANNEL_STATE[channel_name]["rec"]
    current_status_data = _create_mock_response(channel_name, current_rec_status)
    
    logging.info(
        f"Modtog POST /ingest/requestRecordingStatus for '{channel_name}'. "
        f"Returnerer 'rec: {current_status_data['rec']}', tid: {current_status_data['hours']:02d}:{current_status_data['minutes']:02d}:{current_status_data['seconds']:02d}"
    )
    return current_status_data

@app.post("/ingest/errors")
async def get_channel_errors(request: ErrorRequest):
    """
    Returnerer mock error data for en specifik kanal.
    Bruger nu dynamisk error state der cykler mellem 0, 1, og 2 fejl.
    """
    channel_name = request.channel
    
    logging.info(
        f"Modtog POST /ingest/errors for '{channel_name}' (clear: {request.clear})"
    )
    
    if channel_name not in CHANNEL_NAMES:
        logging.warning(f"Modtog POST for ukendt kanal: {channel_name}")
        return {"error": "Channel not found"}
    
    # Tjek om denne kanal har fejl i den globale error state
    if channel_name in GLOBAL_ERROR_CHANNELS:
        return _create_mock_error_response(channel_name)
    else:
        # Ingen fejl for denne kanal
        return {
            "channel": channel_name,
            "name": channel_name,
            "errors": []
        }

@app.post("/ingest/startRecordingWithFilename")
async def start_recording_with_filename(request: StartRecordingRequest):
    """
    Start en specifik kanal - matcher Just In Engine API.
    Skifter til manual mode ved første brug.
    """
    global MANUAL_MODE, AUTO_CYCLER_TASK
    channel_name = request.channel
    
    logging.info(f"Modtog POST /ingest/startRecordingWithFilename for '{channel_name}'")
    logging.debug(f"Proposed filename: '{request.proposed_filename}'")
    logging.debug(f"Metadata: {request.metadata}")
    
    if channel_name not in CHANNEL_NAMES:
        logging.warning(f"Modtog POST for ukendt kanal: {channel_name}")
        return {"error": "Channel not found"}
    
    # Skift til manual mode ved første stop/start kommando
    if not MANUAL_MODE:
        MANUAL_MODE = True
        logging.info("🔧 SKIFTER TIL MANUAL MODE - auto-cycling stoppes!")
        
        # Stop auto cycler task
        if AUTO_CYCLER_TASK and not AUTO_CYCLER_TASK.done():
            AUTO_CYCLER_TASK.cancel()
            try:
                await AUTO_CYCLER_TASK
            except asyncio.CancelledError:
                pass
    
    # Start den angivne kanal
    GLOBAL_CHANNEL_STATE[channel_name]["rec"] = True
    # Set recording start time
    RECORDING_START_TIMES[channel_name] = time.time()
    logging.info(f"✅ Kanal '{channel_name}' startet (rec: true) - starttid sat")
    
    return {"status": "ok", "channel": channel_name, "action": "started"}

@app.post("/ingest/stopRecording")
async def stop_recording(request: StopRecordingRequest):
    """
    Stop en specifik kanal - matcher Just In Engine API.
    Skifter til manual mode ved første brug.
    """
    global MANUAL_MODE, AUTO_CYCLER_TASK
    channel_name = request.channel
    
    logging.info(f"Modtog POST /ingest/stopRecording for '{channel_name}'")
    logging.debug(f"Metadata: {request.metadata}")
    
    if channel_name not in CHANNEL_NAMES:
        logging.warning(f"Modtog POST for ukendt kanal: {channel_name}")
        return {"error": "Channel not found"}
    
    # Skift til manual mode ved første stop/start kommando
    if not MANUAL_MODE:
        MANUAL_MODE = True
        logging.info("🔧 SKIFTER TIL MANUAL MODE - auto-cycling stoppes!")
        
        # Stop auto cycler task
        if AUTO_CYCLER_TASK and not AUTO_CYCLER_TASK.done():
            AUTO_CYCLER_TASK.cancel()
            try:
                await AUTO_CYCLER_TASK
            except asyncio.CancelledError:
                pass
    
    # Stop den angivne kanal
    GLOBAL_CHANNEL_STATE[channel_name]["rec"] = False
    # Remove recording start time
    RECORDING_START_TIMES.pop(channel_name, None)
    logging.info(f"⏹️ Kanal '{channel_name}' stoppet (rec: false) - starttid fjernet")
    
    return {"status": "ok", "channel": channel_name, "action": "stopped"}

@app.post("/mock/reset-auto-mode")
async def reset_auto_mode():
    """
    DEBUG endpoint til at genaktivere auto-cycling mode.
    """
    global MANUAL_MODE, AUTO_CYCLER_TASK
    
    logging.info("🔄 RESET TIL AUTO MODE - genstartes auto-cycling")
    
    # Stop existing task hvis den kører
    if AUTO_CYCLER_TASK and not AUTO_CYCLER_TASK.done():
        AUTO_CYCLER_TASK.cancel()
        try:
            await AUTO_CYCLER_TASK
        except asyncio.CancelledError:
            pass
    
    # Reset til auto mode
    MANUAL_MODE = False
    
    # Start auto cycler igen
    AUTO_CYCLER_TASK = asyncio.create_task(_state_cycler_task())
    
    return {"status": "ok", "message": "Auto-cycling mode restarted"}

@app.get("/mock/status")
async def get_mock_status():
    """
    DEBUG endpoint til at se mock server status.
    """
    recording_channels = [name for name, state in GLOBAL_CHANNEL_STATE.items() if state.get("rec", False)]
    
    return {
        "manual_mode": MANUAL_MODE,
        "auto_cycler_running": AUTO_CYCLER_TASK and not AUTO_CYCLER_TASK.done() if AUTO_CYCLER_TASK else False,
        "total_channels": len(CHANNEL_NAMES),
        "recording_channels": len(recording_channels),
        "recording_channel_names": recording_channels,
        "error_channels": len(GLOBAL_ERROR_CHANNELS),
        "error_channel_names": GLOBAL_ERROR_CHANNELS
    }

# --- Kør serveren ---

if __name__ == "__main__":
    print(f"--- Starter Just In Mock Server på http://localhost:{MOCK_SERVER_PORT} ---")
    print("Tryk CTRL+C for at stoppe.")
    uvicorn.run(app, host="0.0.0.0", port=MOCK_SERVER_PORT, log_level="warning")