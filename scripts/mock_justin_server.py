import asyncio
import logging
import time
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

# --- Pydantic Modeller ---

class ChannelRequest(BaseModel):
    """Matcher den POST-body, vi forventer."""
    channel: str

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

async def _state_cycler_task():
    """
    Baggrunds-task, der cykler Tally-tilstanden hvert 4. sekund.
    """
    logging.info("State Cycler Task startet. Skifter status hver 4. sekund.")
    
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

# --- Kør serveren ---

if __name__ == "__main__":
    print(f"--- Starter Just In Mock Server på http://localhost:{MOCK_SERVER_PORT} ---")
    print("Tryk CTRL+C for at stoppe.")
    uvicorn.run(app, host="0.0.0.0", port=MOCK_SERVER_PORT, log_level="warning")