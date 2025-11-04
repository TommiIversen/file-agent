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

# --- Pydantic Modeller ---

class ChannelRequest(BaseModel):
    """Matcher den POST-body, vi forventer."""
    channel: str

class ErrorRequest(BaseModel):
    """Request model for /ingest/errors endpoint."""
    channel: str
    clear: int = 0

# --- Hjælpefunktioner ---

def _create_mock_response(channel_name: str, rec_status: bool) -> Dict[str, Any]:
    """Genererer den store JSON-respons for en given kanal."""
    return {
        "rec": rec_status,
        "frames": 11,
        "channel": channel_name,
        "hours": 0,
        "seconds": int(time.time()) % 60, # Lidt variation
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
        "name": channel_name,
        "minutes": 24
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
    """
    logging.info("State Cycler Task startet. Cykler recording + error status hver 4. sekund.")
    
    while True:
        try:
            # --- Tilstand 1: ALLE SLUKKET ---
            logging.info("--- STATE 1: ALLE KANALER 'rec: false' ---")
            for name in CHANNEL_NAMES:
                GLOBAL_CHANNEL_STATE[name]["rec"] = False
            await asyncio.sleep(STATE_DURATION_SECONDS)

            # --- Tilstand 2: ALLE TÆNDT ---
            logging.info("--- STATE 2: ALLE KANALER 'rec: true' ---")
            for name in CHANNEL_NAMES:
                GLOBAL_CHANNEL_STATE[name]["rec"] = True
            await asyncio.sleep(STATE_DURATION_SECONDS)

            # --- Tilstand 3: ÉN SLUKKET (fejl-tilstand) ---
            logging.info("--- STATE 3: KAM_8 'rec: false', RESTEN 'rec: true' ---")
            for name in CHANNEL_NAMES:
                if name == "KAM_8":
                    GLOBAL_CHANNEL_STATE[name]["rec"] = False
                else:
                    GLOBAL_CHANNEL_STATE[name]["rec"] = True
            await asyncio.sleep(STATE_DURATION_SECONDS)

            # --- ERROR CYCLES ---
            
            # Error Cycle 1: Ingen fejl
            logging.info("--- ERROR CYCLE 1: INGEN FEJL ---")
            GLOBAL_ERROR_CHANNELS.clear()
            await asyncio.sleep(STATE_DURATION_SECONDS)

            # Error Cycle 2: 1 fejl på random kanal
            logging.info("--- ERROR CYCLE 2: 1 FEJL PÅ RANDOM KANAL ---")
            GLOBAL_ERROR_CHANNELS.clear()
            random_channel = random.choice(CHANNEL_NAMES)
            GLOBAL_ERROR_CHANNELS.append(random_channel)
            logging.info(f"Fejl på: {random_channel}")
            await asyncio.sleep(STATE_DURATION_SECONDS)

            # Error Cycle 3: 2 fejl på random kanaler
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


# --- FastAPI App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Håndterer opstart og nedlukning af serveren."""
    
    # Opstart: Initialiser den globale tilstand
    logging.info("Mock-server starter... Initialiserer global tilstand.")
    for name in CHANNEL_NAMES:
        # Start med at alt er slukket
        GLOBAL_CHANNEL_STATE[name] = _create_mock_response(name, rec_status=False)
    
    # Start baggrunds-tasken
    cycler_task = asyncio.create_task(_state_cycler_task())
    
    yield # App'en kører
    
    # Nedlukning: Stop baggrunds-tasken
    logging.info("Mock-server lukker ned... Stopper baggrunds-task.")
    cycler_task.cancel()
    try:
        await cycler_task
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
    fra den globale tilstand.
    """
    channel_name = request.channel
    
    if channel_name not in GLOBAL_CHANNEL_STATE:
        logging.warning(f"Modtog POST for ukendt kanal: {channel_name}")
        return {"error": "Channel not found"}

    # Hent den nuværende, opdaterede status fra den globale dict
    current_status_data = GLOBAL_CHANNEL_STATE[channel_name]
    
    logging.info(
        f"Modtog POST /ingest/requestRecordingStatus for '{channel_name}'. "
        f"Returnerer 'rec: {current_status_data['rec']}'"
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

# --- Kør serveren ---

if __name__ == "__main__":
    print(f"--- Starter Just In Mock Server på http://localhost:{MOCK_SERVER_PORT} ---")
    print("Tryk CTRL+C for at stoppe.")
    uvicorn.run(app, host="0.0.0.0", port=MOCK_SERVER_PORT, log_level="warning")