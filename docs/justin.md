# Just In Engine API Documentation
This document describes the API endpoints available for interacting with the Just In Engine. The Just In Engine provides various functionalities including recording status, active channels, and error reporting.

## API Endpoints


http://10.65.79.29:8080/ingest/requestRecordingStatus

Response body
Download
```json
{
  "rec": false,
  "frames": 11,
  "channel": "KAM_1",
  "hours": 0,
  "seconds": 47,
  "options": {
    "TOAJustInEngineTimecodeSource": 6,
    "TOAJustInEngineLicenseStatus": true,
    "TOAJustInEngineRecordingMode": 1,
    "TOAJustInEngineAlternativeStartTimecodeFrames": 0,
    "TOAJustInEngineTimecodeOffset": 0,
    "TOAJustInEngineVideoSignalAvailable": true,
    "TOAJustInEngineAlternativeStopTimecodeFrames": 0,
    "TOAJustInEngineRecordingError": false,
    "TOAJustInEngineLiveCutEnabled": false,
    "TOAJustInEngineMetadataWritingOption": 1,
    "TOAJustInEngineStartTimecodeFrames": 0,
    "TOAJustInEngineAlternativeStartTimecodeActive": false,
    "TOAJustInEngineFramerate": 2500,
    "TOAJustInEngineAlternativeStopTimecodeActive": false
  },
  "name": "KAM_1",
  "minutes": 24
}
```


http://10.65.79.29:8080/ingest/activeChannels
```json
{
  "channel-names": [
    "KAM_1",
    "KAM_2",
    "KAM_3",
    "KAM_4",
    "KAM_5",
    "KAM_6",
    "KAM_7",
    "KAM_8"
  ]
}
```



http://10.65.79.29:8080/ingest/errors
Note: EPOC alway has wrong year in date field ; fredag d. 4. november 1994 kl. 05:30:51.578 GMT+01:00
```json
{
  "channel": "KAM_4",
  "name": "KAM_4",
  "errors": [
    {
      "date": 783923451.578716,  
      "errorCode": -8995,
      "errorDomain": "TOAErrorDomainGeneric",
      "errorUIDescription": "No signal",
      "errorUserInfo": {
        "NSLocalizedDescription": "No signal, please check the incoming video format."
      },
      "errorType": 3
    }
  ]
}
```





# Fase 1: Fundament og Konfiguration
Mål: Oprette de nye domæner og gøre konfigurationen klar.

## Opdater Konfiguration:

Fil: app/config.py

Handling: Tilføj de nye API-endpoints til din Settings-klasse.

```python
class Settings(BaseSettings):
    # ... (dine eksisterende settings)

    # --- NYE INDSTILLINGER ---
    JUSTIN_API_BASE_URL: str = Field(
        default="http://localhost:8080",
        description="Base URL for Just In Engine API'en"
    )
    TALLY_LIGHT_API_URL: str = Field(
        default="http://localhost:8001/api/switch", # Antaget eksempel-URL
        description="Base URL til IP Power Switch (Tally Light)"
    )
```
## Opret Domæne-mapper:

Opret app/domains/ingest_monitor/

Opret app/domains/tally_light/

## Definer Datamodeller:

Fil: app/domains/ingest_monitor/models.py (Ny fil)

Handling: Opret Pydantic-modeller, der matcher API-svarene fra Just In, så du arbejder med typer, ikke rå dictionaries.

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class JustInOptions(BaseModel):
    TOAJustInEngineVideoSignalAvailable: bool = True
    TOAJustInEngineRecordingError: bool = False
    # ... (tilføj andre felter efter behov) ...

class JustInRecordingStatus(BaseModel):
    rec: bool
    channel: str
    options: JustInOptions

class JustInActiveChannels(BaseModel):
    channel_names: List[str] = Field(..., alias="channel-names")

class JustInError(BaseModel):
    date: float
    errorCode: int
    errorUIDescription: str

class JustInErrors(BaseModel):
    channel: str
    errors: List[JustInError]

class ChannelState(BaseModel):
    """Vores interne 'Single Source of Truth' for en kanal."""
    name: str
    is_recording: bool = False
    has_signal: bool = True
    has_errors: bool = False
    last_errors: List[JustInError] = []
```


# Fase 2: Opret IngestMonitor Service (Data-indsamleren)
Mål: Byg den kerne-service, der kører i baggrunden, henter data fra Just In API'en og holder en intern "cache" af live-status.

## Definer Nye Events:

Fil: app/domains/ingest_monitor/events.py (Ny fil)

Handling: Definer de events, denne service vil publicere.

```python
from dataclasses import dataclass
from app.core.events.domain_event import DomainEvent

@dataclass(frozen=True)
class ChannelRecordingStartedEvent(DomainEvent):
    channel_name: str

@dataclass(frozen=True)
class ChannelRecordingStoppedEvent(DomainEvent):
    channel_name: str

@dataclass(frozen=True)
class ChannelErrorDetectedEvent(DomainEvent):
    channel_name: str
    error_message: str

@dataclass(frozen=True)
class IngestStatusUpdatedEvent(DomainEvent):
    """En samlet event til UI'et med status for alle kanaler."""
    status_snapshot: Dict[str, dict] # f.eks. {"KAM_1": {"is_recording": true, ...}}
```
## Opret Servicen:

Fil: app/domains/ingest_monitor/service.py (Ny fil)

Handling: Denne service vil køre to parallelle loops: En hurtig (for rec status) og en langsom (for errors).

```python
import asyncio
import logging
import httpx
from typing import Dict, List, Optional
from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from .models import ChannelState, JustInActiveChannels, JustInRecordingStatus, JustInErrors
from .events import (
    ChannelRecordingStartedEvent, ChannelRecordingStoppedEvent, 
    ChannelErrorDetectedEvent, IngestStatusUpdatedEvent
)

class IngestMonitorService:
    def __init__(self, settings: Settings, event_bus: DomainEventBus):
        self._settings = settings
        self._event_bus = event_bus
        self._client = httpx.AsyncClient(base_url=settings.JUSTIN_API_BASE_URL, timeout=2.0)
        self._status_cache: Dict[str, ChannelState] = {}
        self._running = False

        # Kør den hurtige "tally"-polling hvert 2. sekund
        self._fast_poll_interval = 2.0 
        # Kør den langsomme "error"-polling hvert 30. sekund
        self._slow_poll_interval = 30.0

    def get_status_cache(self) -> Dict[str, dict]:
        """Returnerer et snapshot af den nuværende cache til UI'et."""
        return {name: state.model_dump() for name, state in self._status_cache.items()}

    async def start_monitoring(self):
        if self._running: return
        self._running = True
        logging.info("IngestMonitorService starter...")

        # Start de to loops parallelt
        self._fast_loop_task = asyncio.create_task(self._fast_polling_loop())
        self._slow_loop_task = asyncio.create_task(self._slow_polling_loop())

    async def stop_monitoring(self):
        self._running = False
        if self._fast_loop_task: self._fast_loop_task.cancel()
        if self._slow_loop_task: self._slow_loop_task.cancel()
        await self._client.aclose()
        logging.info("IngestMonitorService stoppet.")

    async def _fast_polling_loop(self):
        """Henter 'rec' status hvert 2. sekund."""
        while self._running:
            try:
                await self._fetch_all_channel_statuses()
            except Exception as e:
                logging.error(f"Fejl i IngestMonitor fast_polling_loop: {e}")
            await asyncio.sleep(self._fast_poll_interval)

    async def _slow_polling_loop(self):
        """Henter 'errors' hvert 30. sekund."""
        while self._running:
            try:
                await self._fetch_all_channel_errors()
            except Exception as e:
                logging.error(f"Fejl i IngestMonitor slow_polling_loop: {e}")
            await asyncio.sleep(self._slow_poll_interval)

    async def _fetch_all_channel_statuses(self):
        """Henter status for alle kanaler parallelt (Fan-out/Fan-in)."""
        try:
            # 1. Hent den samlede kanalliste
            response = await self._client.get("/ingest/activeChannels")
            response.raise_for_status()
            channel_data = JustInActiveChannels.model_validate(response.json())
            channel_names = channel_data.channel_names

            # 2. Opret en task for hver kanal
            async with asyncio.TaskGroup() as tg:
                tasks = [
                    tg.create_task(self._fetch_single_channel_status(name)) 
                    for name in channel_names
                ]

            # 3. Saml resultater og opdater cache
            new_statuses: List[ChannelState] = [task.result() for task in tasks if task.result()]
            events_to_publish = self._update_cache_and_detect_changes(new_statuses)

            # 4. Publicer events
            for event in events_to_publish:
                await self._event_bus.publish(event)

            # Publicer den samlede snapshot-event til UI
            await self._event_bus.publish(IngestStatusUpdatedEvent(
                status_snapshot=self.get_status_cache()
            ))

        except httpx.RequestError as e:
            logging.warning(f"Kunne ikke hente activeChannels: {e}")
        except Exception as e:
            logging.error(f"Fejl i _fetch_all_channel_statuses: {e}")

    async def _fetch_single_channel_status(self, channel_name: str) -> Optional[ChannelState]:
        """Henter status for én enkelt kanal."""
        try:
            response = await self._client.get(f"/ingest/requestRecordingStatus?channel={channel_name}")
            status_data = JustInRecordingStatus.model_validate(response.json())

            # Opdater eller opret den interne state
            state = self._status_cache.get(channel_name, ChannelState(name=channel_name))
            state.is_recording = status_data.rec
            state.has_signal = status_data.options.TOAJustInEngineVideoSignalAvailable
            # Note: Fejlstatus nulstilles kun af den langsomme error-loop

            return state
        except Exception as e:
            logging.warning(f"Kunne ikke hente status for {channel_name}: {e}")
            return None

    def _update_cache_and_detect_changes(self, new_states: List[ChannelState]) -> List[DomainEvent]:
        """Sammenligner ny state med cachen og genererer Tally-events."""
        events = []
        for new_state in new_states:
            channel_name = new_state.name
            old_state = self._status_cache.get(channel_name)

            if old_state and old_state.is_recording != new_state.is_recording:
                if new_state.is_recording:
                    events.append(ChannelRecordingStartedEvent(channel_name=channel_name))
                else:
                    events.append(ChannelRecordingStoppedEvent(channel_name=channel_name))

            # Opdater cachen
            self._status_cache[channel_name] = new_state
        return events

    async def _fetch_all_channel_errors(self):
        """Henter fejlstatus for alle kanaler parallelt (langsom loop)."""
        channel_names = list(self._status_cache.keys())
        if not channel_names:
            return # Ingen kanaler at tjekke

        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(self._fetch_single_channel_error(name)) 
                for name in channel_names
            ]

        # Opdater cache med fejl-info
        for task in tasks:
            if task.result():
                channel_name, errors, has_new_error = task.result()
                if channel_name in self._status_cache:
                    self._status_cache[channel_name].has_errors = bool(errors)
                    self._status_cache[channel_name].last_errors = errors
                    if has_new_error:
                        await self._event_bus.publish(ChannelErrorDetectedEvent(
                            channel_name=channel_name,
                            error_message=errors[0].errorUIDescription
                        ))

    async def _fetch_single_channel_error(self, channel_name: str) -> Optional[tuple[str, List[JustInError], bool]]:
        """Henter fejl for én kanal og tjekker om der er NYE fejl."""
        try:
            response = await self._client.get(f"/ingest/errors?channel={channel_name}")
            error_data = JustInErrors.model_validate(response.json())

            old_errors = self._status_cache.get(channel_name, ChannelState(name=channel_name)).last_errors
            # Simpel tjek: er den nyeste fejl forskellig fra den gamle nyeste fejl?
            has_new_error = False
            if error_data.errors and (not old_errors or error_data.errors[0].date != old_errors[0].date):
                has_new_error = True

            return channel_name, error_data.errors, has_new_error
        except Exception as e:
            logging.warning(f"Kunne ikke hente fejl for {channel_name}: {e}")
            return None
```



# Fase 3: Opret TallyLight Domænet (Modificeret)
Fase 3: Opret TallyLight Domænet (KORRIGERET)
Mål: Oprette en "stateful" lytter, der abonnerer på det samlede IngestStatusUpdatedEvent og administrerer en enkelt Tally-lampe (med /on og /off) for at vise tre tilstande: Solidt Lys (alle optager), Blink (nogle optager) eller Slukket (ingen optager).

Opret Håndterings-filen:

Fil: app/domains/tally_light/event_handlers.py (Ny fil)

Implementer TallyLightEventHandler (Stateful Version):

Handling: Erstat den simple handler med denne nye, stateful version, der administrerer en baggrunds-blinker-task.

Python

import asyncio
import logging
import httpx
from enum import Enum
from typing import Optional
from app.config import Settings
from app.domains.ingest_monitor.events import IngestStatusUpdatedEvent

class TallyState(Enum):
    """Definerer de 3 ønskede tilstande for den fælles Tally-lampe."""
    OFF = "off"
    SOLID_ON = "on"
    BLINKING = "blink"

class TallyLightEventHandler:
    """
    Administrerer den fælles Tally-lampe ved at starte/stoppe en
    baggrunds-blinker-task baseret på den samlede optagestatus.
    """
    def __init__(self, settings: Settings):
        self._client = httpx.AsyncClient(base_url=settings.TALLY_LIGHT_API_URL, timeout=1.0)
        self._current_tally_state: TallyState = TallyState.OFF
        self._blinker_task: Optional[asyncio.Task] = None
        self._blink_interval_sec: float = 0.5  # 500ms tænd, 500ms sluk
        self._lock = asyncio.Lock() # Beskytter adgang til _blinker_task
        logging.info("TallyLightEventHandler initialiseret (med Software Blinker-logik)")

    async def handle_ingest_status_update(self, event: IngestStatusUpdatedEvent):
        """
        Modtager det komplette status-snapshot hvert 2. sekund
        og opdaterer Tally-lampens tilstand.
        """
        snapshot = event.status_snapshot

        # 1. Bestem den ønskede nye tilstand
        new_state: TallyState
        if not snapshot:
            new_state = TallyState.OFF
        else:
            total_channels = len(snapshot)
            recording_channels = sum(
                1 for state in snapshot.values() if state.get("is_recording", False)
            )

            if recording_channels == 0:
                new_state = TallyState.OFF
            elif recording_channels == total_channels:
                new_state = TallyState.SOLID_ON # Alle optager
            else:
                new_state = TallyState.BLINKING # Mindst én, men ikke alle, optager

        # 2. Anvend kun ændringen, hvis den er ny
        if new_state != self._current_tally_state:
            await self._update_tally_state(
                new_state, 
                f"{recording_channels}/{total_channels} optager"
            )

    async def _update_tally_state(self, new_state: TallyState, reason: str):
        """
        Håndterer overgangen mellem OFF, SOLID_ON, og BLINKING
        ved at administrere blinker-tasken.
        """
        async with self._lock:
            if new_state == self._current_tally_state:
                return # En anden event nåede at ændre den i mellemtiden

            current_state_str = self._current_tally_state.value
            new_state_str = new_state.value
            logging.info(f"Tally-status ændret: {current_state_str} -> {new_state_str} (Årsag: {reason})")

            # 1. Stop altid den gamle blinker-task (hvis den kører)
            if self._blinker_task and not self._blinker_task.done():
                self._blinker_task.cancel()
                try:
                    await self._blinker_task # Vent på at den lukker ned og slukker lyset
                except asyncio.CancelledError:
                    pass # Forventet
            self._blinker_task = None

            # 2. Sæt den nye tilstand
            try:
                if new_state == TallyState.SOLID_ON:
                    await self._client.post("/on")
                elif new_state == TallyState.OFF:
                    await self._client.post("/off")
                elif new_state == TallyState.BLINKING:
                    # Start den nye blinker-task i baggrunden
                    self._blinker_task = asyncio.create_task(self._blinker_loop())

                self._current_tally_state = new_state # Gem den nye tilstand

            except httpx.RequestError as e:
                logging.error(f"Kunne ikke opdatere Tally-lys til {new_state_str}: {e}")
                # Vi opdaterer ikke _current_tally_state, så den prøver igen ved næste event

    async def _blinker_loop(self):
        """Evig løkke, der tænder/slukker lyset via /on og /off."""
        try:
            while True:
                await self._client.post("/on")
                await asyncio.sleep(self._blink_interval_sec)
                await self._client.post("/off")
                await asyncio.sleep(self._blink_interval_sec)
        except asyncio.CancelledError:
            # Vigtig oprydning: Sørg for at slukke lyset, når blink stoppes.
            try:
                await self._client.post("/off")
                logging.info("Blinker-task stoppet, lyset er slukket.")
            except httpx.RequestError as e:
                logging.error(f"Kunne ikke slukke Tally-lys under blink-stop: {e}")
            raise # Re-raise CancelledError
        except Exception as e:
            logging.error(f"Fejl i blinker-loop: {e}")
            # Sæt tilstanden tilbage til OFF, så den kan genstartes
            self._current_tally_state = TallyState.OFF

    async def stop_worker(self):
        """Kaldes fra main.py lifespan for at sikre ren nedlukning."""
        logging.info("Stopper TallyLightEventHandler (slukker lys)...")
        await self._update_tally_state(TallyState.OFF, "Applikation lukker ned")
        logging.info("TallyLightEventHandler stoppet.")
Opret Registrerings-fil:

Fil: app/domains/tally_light/registration.py (Ny fil)

Handling: Sørg for, at den nye handler abonnerer på IngestStatusUpdatedEvent.

Python

import logging
from app.core.events.event_bus import DomainEventBus
from app.core.cqrs.command_bus import CommandBus
from app.domains.ingest_monitor.events import IngestStatusUpdatedEvent
from .event_handlers import TallyLightEventHandler

def register_tally_light_domain(
    command_bus: CommandBus, 
    event_bus: DomainEventBus, 
    handler: TallyLightEventHandler # Modtag den instansierede handler
):
    """Registrerer alle event-abonnementer for TallyLight-domænet."""
    logging.info("Registrerer 'TallyLight' domæne handlers...")

    # Abonner på den samlede snapshot-event
    event_bus.subscribe(
        IngestStatusUpdatedEvent, 
        handler.handle_ingest_status_update
    )
Opdater app/dependencies.py:

Handling: Tilføj en getter for den nye TallyLightEventHandler.

Python

# ... (andre imports)
from app.domains.tally_light.event_handlers import TallyLightEventHandler

def get_tally_light_event_handler() -> TallyLightEventHandler:
    if "tally_light_event_handler" not in _singletons:
        _singletons["tally_light_event_handler"] = TallyLightEventHandler(
            settings=get_settings()
        )
    return _singletons["tally_light_event_handler"]
Opdater app/main.py:

Handling: Sørg for at registrere domænet og vigtigst af alt, kald stop_worker() ved nedlukning.

Python

# ... (imports)
from app.domains.tally_light.registration import register_tally_light_domain
from app.dependencies import get_tally_light_event_handler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... (al din eksisterende startup-kode) ...

    tally_handler = get_tally_light_event_handler()
    register_tally_light_domain(command_bus, event_bus, tally_handler)

    yield # Applikationen kører

    # --- NEDLUKNINGS-LOGIK ---
    logging.info("Applikation lukker ned... Stopper Tally-lys...")
    await tally_handler.stop_worker()
    # ... (anden nedluknings-logik) ...

# Fase 4: Opret Frontend API'et (CQRS)
Mål: Gøre IngestMonitor's cachede data tilgængelige for UI'et via et Query.

## Definer Query:

Fil: app/domains/ingest_monitor/queries.py (Ny fil)

```python
@dataclass
class GetIngestStatusQuery:
    """Henter det cachede snapshot af alle kanalers status."""
    pass
```
## Opret Query Handler:

Fil: app/domains/ingest_monitor/handlers.py (Ny fil)

```python
from .queries import GetIngestStatusQuery
from .service import IngestMonitorService
from typing import Dict

class GetIngestStatusQueryHandler:
    def __init__(self, ingest_monitor_service: IngestMonitorService):
        self._service = ingest_monitor_service

    async def handle(self, query: GetIngestStatusQuery) -> Dict[str, dict]:
        # Henter direkte fra servicens cache - lynhurtigt
        return self._service.get_status_cache()
```
## Opret API Endpoint:

Fil: app/domains/ingest_monitor/api.py (Ny fil)

```python
from fastapi import APIRouter, Depends
from app.core.cqrs.query_bus import QueryBus
from app.dependencies import get_query_bus
from .queries import GetIngestStatusQuery

router = APIRouter(prefix="/api/ingest", tags=["Ingest Monitor"])

@router.get("/status")
async def get_ingest_status(query_bus: QueryBus = Depends(get_query_bus)):
    """Henter live-status for alle ingest-kanaler."""
    return await query_bus.execute(GetIngestStatusQuery())
```


# Fase 5: Registrering og Opstart
Mål: Kable det hele sammen i DI-containeren og main.py.

## Opret Registrerings-filer:

app/domains/ingest_monitor/registration.py

app/domains/tally_light/registration.py

## Opdater app/dependencies.py:

Tilføj get_ingest_monitor_service() (som singleton).

Tilføj get_tally_light_event_handler() (som singleton).

## Opdater app/main.py:

lifespan:

Kald register_ingest_monitor_domain(...) (registrerer Query Handler).

Kald register_tally_light_domain(...) (registrerer Event Handlers til Tally-events).

Hent IngestMonitorService og kald asyncio.create_task(ingest_monitor_service.start_monitoring()).

app:

app.include_router(ingest_api_router)

## Opdater PresentationEventHandlers:

Fil: app/domains/presentation/event_handlers.py

Handling: Få denne handler til at abonnere på IngestStatusUpdatedEvent og ChannelErrorDetectedEvent.

Når den modtager disse, skal den formatere en ny WebSocket-besked (f.eks. ingest_status_update eller new_event_log) og broadcaste den, så UI'et opdateres live.


# Fase 6: Frontend UI (Manuelt Arbejde)
## Opret ingestStore.js:

I init(): Kald fetch('/api/ingest/status') for at få den indledende data.

## Opdater messageHandler.js:

Tilføj case "ingest_status_update": til at opdatere ingestStore.js.

Tilføj case "new_event_log": til at tilføje fejlen til din GlobalEventLogger (eller en ny log-store).

## Byg UI-panelet:

Brug x-for til at iterere over kanalerne i ingestStore.js.

Vis is_recording (som en rød/grøn prik).

Vis has_errors (som et advarsels-ikon).

Vis den nye event-log.