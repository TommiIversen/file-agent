# Recording Session Plan — Output Folder Grouping

## Problem

Justin optager 8 video-strømme (`.mxf`) + audio (`.wav`) samtidigt. Filnavne indeholder tidsstempel (`HHMMSS`), men kanalerne starter med ±1 sekunds forskydning. Template-systemet parser `{time}` fra hvert filnavn individuelt → filer fra **samme optagelsessession** ender i **forskellige output-mapper** (f.eks. `/120530/` og `/120531/`).

## Løsning

Indfør et `RecordingSession`-koncept i `ingest_monitor`-domænet der fanger kanonisk session-starttid. Tag `TrackedFile` med `session_time` ved discovery, propagér til copy pipeline, og eksponer ny `{session_time}` variabel i template engine.

## Arkitektur-regler (KRITISKE)

1. **`app/core/`** må ALDRIG importere fra `app/domains/`
2. **`app/domains/X`** må ALDRIG importere direkte fra `app/domains/Y` — brug EventBus/QueryBus
3. **State-ændringer** SKAL bruge `FileStateMachine.transition()`
4. **Al ny feature-kode** skal bestå: `pytest --ignore=scripts`, `mypy app/`, `lint-imports`
5. **Ingen `# type: ignore` eller `# noqa`**

---

## Fase 1: RecordingSessionTracker i ingest_monitor

### Step 1.1: Opret `RecordingSession` dataclass + `RecordingSessionTracker`

**Opret ny fil:** `app/domains/ingest_monitor/session_tracker.py`

```python
"""
Recording Session Tracker

Tracks recording sessions across Justin channels.
A session starts when the first channel begins recording and ends
when all channels have stopped (after a configurable grace period).

All files discovered during or shortly after a session share the same
canonical session_time, ensuring they land in the same output folder.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RecordingSession:
    """Represents a single recording session spanning multiple channels."""

    session_id: str
    session_time: str  # "HHMMSS" formatted from started_at
    started_at: datetime
    ended_at: Optional[datetime] = None
    channel_names: set[str] = field(default_factory=set)

    @property
    def is_active(self) -> bool:
        return self.ended_at is None


class RecordingSessionTracker:
    """
    Tracks the lifecycle of recording sessions.

    A session is created when the first channel starts recording.
    It ends when ALL channels have stopped AND the grace period has elapsed.
    The grace period prevents accidental session splits from quick restart cycles.

    Usage:
        tracker = RecordingSessionTracker(grace_period_seconds=5.0, history_minutes=120)
        tracker.handle_channel_started("KAM_1")  # → creates session
        tracker.handle_channel_started("KAM_2")  # → same session
        ...
        tracker.handle_channel_stopped("KAM_1", active_recording_channels={"KAM_2"})
        tracker.handle_channel_stopped("KAM_2", active_recording_channels=set())
        # → grace period starts, session ends after 5s
    """

    def __init__(
        self,
        grace_period_seconds: float = 5.0,
        history_minutes: int = 120,
    ) -> None:
        self._grace_period_seconds = grace_period_seconds
        self._history_minutes = history_minutes
        self._active_session: Optional[RecordingSession] = None
        self._recent_sessions: list[RecordingSession] = []
        self._grace_period_task: Optional[asyncio.Task[None]] = None

    @property
    def active_session(self) -> Optional[RecordingSession]:
        return self._active_session

    @property
    def recent_sessions(self) -> list[RecordingSession]:
        return list(self._recent_sessions)

    def handle_channel_started(self, channel_name: str) -> None:
        """
        Handle a channel starting recording.

        If no active session exists, a new session is created.
        If the grace period timer is running (all channels were stopped briefly),
        the timer is cancelled and the existing session continues.
        """
        # Cancel grace period if running (quick restart scenario)
        if self._grace_period_task is not None and not self._grace_period_task.done():
            self._grace_period_task.cancel()
            self._grace_period_task = None
            logger.info(
                "Grace period cancelled — session %s continues (channel %s restarted)",
                self._active_session.session_id[:8] if self._active_session else "?",
                channel_name,
            )

        if self._active_session is None:
            # Create new session
            now = datetime.now(timezone.utc)
            session_time = now.strftime("%H%M%S")
            self._active_session = RecordingSession(
                session_id=str(uuid.uuid4()),
                session_time=session_time,
                started_at=now,
                channel_names={channel_name},
            )
            logger.info(
                "Recording session started: id=%s, session_time=%s, first_channel=%s",
                self._active_session.session_id[:8],
                session_time,
                channel_name,
            )
        else:
            # Add channel to existing session
            self._active_session.channel_names.add(channel_name)
            logger.debug(
                "Channel %s joined session %s (channels: %d)",
                channel_name,
                self._active_session.session_id[:8],
                len(self._active_session.channel_names),
            )

    def handle_channel_stopped(
        self, channel_name: str, active_recording_channels: set[str]
    ) -> None:
        """
        Handle a channel stopping recording.

        When all channels have stopped, a grace period timer starts.
        If no channel restarts before the grace period elapses, the session ends.

        Args:
            channel_name: The channel that stopped.
            active_recording_channels: Set of channels STILL recording
                (after this stop). Empty set means all stopped.
        """
        if self._active_session is None:
            return

        if not active_recording_channels:
            # All channels stopped — start grace period
            logger.info(
                "All channels stopped in session %s — grace period %.1fs started",
                self._active_session.session_id[:8],
                self._grace_period_seconds,
            )
            self._grace_period_task = asyncio.create_task(
                self._end_session_after_grace_period()
            )

    async def _end_session_after_grace_period(self) -> None:
        """Wait for grace period, then finalize the active session."""
        try:
            await asyncio.sleep(self._grace_period_seconds)
        except asyncio.CancelledError:
            return  # Grace period cancelled (channel restarted)

        if self._active_session is not None:
            self._active_session.ended_at = datetime.now(timezone.utc)
            self._recent_sessions.append(self._active_session)
            logger.info(
                "Recording session ended: id=%s, session_time=%s, channels=%s",
                self._active_session.session_id[:8],
                self._active_session.session_time,
                sorted(self._active_session.channel_names),
            )
            self._active_session = None
            self._prune_old_sessions()

        self._grace_period_task = None

    def _prune_old_sessions(self) -> None:
        """Remove sessions older than history_minutes."""
        if not self._recent_sessions:
            return
        cutoff = datetime.now(timezone.utc).timestamp() - (
            self._history_minutes * 60
        )
        self._recent_sessions = [
            s
            for s in self._recent_sessions
            if s.started_at.timestamp() > cutoff
        ]

    def get_session_time(
        self, file_creation_time: Optional[datetime] = None
    ) -> Optional[str]:
        """
        Get the canonical session_time for a file.

        1. If there is an active session → return its session_time.
        2. If file_creation_time is provided → search recent sessions
           where the file was created during (or shortly after) the session.
        3. Otherwise → return None (no session info available).
        """
        # Active session takes priority
        if self._active_session is not None:
            return self._active_session.session_time

        # Search recent sessions by file creation time
        if file_creation_time is not None:
            creation_ts = file_creation_time.timestamp()
            # Allow a 60-second margin after session end for late-arriving files
            margin_seconds = 60.0

            for session in reversed(self._recent_sessions):
                start_ts = session.started_at.timestamp()
                end_ts = (
                    session.ended_at.timestamp() + margin_seconds
                    if session.ended_at
                    else start_ts + margin_seconds
                )
                if start_ts <= creation_ts <= end_ts:
                    logger.debug(
                        "File (created %s) matched recent session %s (time=%s)",
                        file_creation_time,
                        session.session_id[:8],
                        session.session_time,
                    )
                    return session.session_time

        return None
```

**Verifikation:** Filen oprettes. Ingen imports fra andre domæner — kun stdlib + core.

---

### Step 1.2: Tilføj config-felter

**Fil:** `app/config.py`

Find sektionen med `audio_filename_from_justin` (sidst i audio-settings) og tilføj **efter** den:

```python
    # Recording session tracking
    recording_session_grace_period_seconds: float = 5.0
    recording_session_history_minutes: int = 120
```

De nye felter skal sidde efter `audio_filename_from_justin: bool = True` linjen i `Settings`-klassen.

**Verifikation:** `mypy app/config.py` bestået.

---

### Step 1.3: Tilføj events

**Fil:** `app/core/events/ingest_events.py`

Tilføj i **bunden** af filen (efter `AutoStopTriggeredEvent`):

```python
@dataclass(frozen=True)
class RecordingSessionStartedEvent(DomainEvent):
    """Published when a new recording session begins (first channel starts)."""
    session_id: str
    session_time: str  # "HHMMSS"


@dataclass(frozen=True)
class RecordingSessionEndedEvent(DomainEvent):
    """Published when a recording session ends (all channels stopped + grace period elapsed)."""
    session_id: str
```

**Verifikation:** `mypy app/core/events/ingest_events.py` bestået.

---

### Step 1.4: Tilføj query-kontrakt

**Fil:** `app/core/cqrs/shared_queries.py`

Tilføj i **bunden** af filen (efter `GetCurrentFilenameQuery`):

```python
@dataclass
class GetRecordingSessionTimeQuery(Query):
    """Query for the canonical session time of the current or recent recording.

    Dispatched by file_discovery, handled by ingest_monitor domain.
    Returns HHMMSS string or None if no session is active/matched.
    """
    file_creation_time: Optional[datetime] = None
```

Tilføj `from datetime import datetime` øverst sammen med de eksisterende imports. Præcis tilføj det til den eksisterende import-sektion:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.core.cqrs.query import Query
```

**Verifikation:** `mypy app/core/cqrs/shared_queries.py` bestået.

---

### Step 1.5: Wire RecordingSessionTracker ind i IngestStateService

**Fil:** `app/domains/ingest_monitor/state_service.py`

**1) Import:**
Tilføj i toppen (blandt eksisterende domain-imports):

```python
from .session_tracker import RecordingSessionTracker
```

**2) __init__ ændring:**
Tilføj nye parametre til `__init__()` signaturen:

Nuværende signatur:
```python
def __init__(
    self,
    event_bus: DomainEventBus,
    auto_stop_minutes: int = 0,
    auto_stop_warning_minutes: int = 5,
):
```

Ny signatur:
```python
def __init__(
    self,
    event_bus: DomainEventBus,
    auto_stop_minutes: int = 0,
    auto_stop_warning_minutes: int = 5,
    session_tracker: RecordingSessionTracker | None = None,
):
```

Tilføj i `__init__()` body (efter `self._auto_stop_triggered: bool = False`):

```python
        # Recording session tracking
        self._session_tracker = session_tracker
```

**3) _detect_changes() ændring:**
I `_detect_changes()` metoden, tilføj session tracker kald **efter** at events er tilføjet til listen. Dvs. efter den eksisterende recording/signal detections-blok, men **før** `return events`:

Find denne kode:
```python
        # Detect signal status changes
        if old_state.has_signal != new_state.has_signal:
            if new_state.has_signal:
                events.append(ChannelSignalRestoredEvent(channel_name=new_state.name))
                logging.info(f"Channel {new_state.name} signal restored")
            else:
                events.append(ChannelSignalLostEvent(channel_name=new_state.name))
                logging.warning(f"Channel {new_state.name} signal lost")

        return events
```

Ændr til:
```python
        # Detect signal status changes
        if old_state.has_signal != new_state.has_signal:
            if new_state.has_signal:
                events.append(ChannelSignalRestoredEvent(channel_name=new_state.name))
                logging.info(f"Channel {new_state.name} signal restored")
            else:
                events.append(ChannelSignalLostEvent(channel_name=new_state.name))
                logging.warning(f"Channel {new_state.name} signal lost")

        # Update session tracker on recording changes
        if self._session_tracker and old_state.is_recording != new_state.is_recording:
            if new_state.is_recording:
                self._session_tracker.handle_channel_started(new_state.name)
            else:
                # Determine which channels are still recording
                active_recording = {
                    name
                    for name, state in self._status_cache.items()
                    if state.is_recording and name != new_state.name
                }
                self._session_tracker.handle_channel_stopped(
                    new_state.name, active_recording
                )

        return events
```

**VIGTIGT:** `_detect_changes()` kaldes **før** `_status_cache` opdateres med `new_state`. Tjek dette: Metoden modtager `old_state` og `new_state`, og kaldet til `self._status_cache.items()` vil returnere den **endnu-ikke-opdaterede** cache. Det betyder `new_state.name` stadig har den **gamle** status i cachen. Vi skal derfor ekskludere `new_state.name` fra aktive kanaler og manuelt vurdere.  

Korrekt: Vi bruger `state.is_recording and name != new_state.name`. Da `new_state.is_recording` er `False` i stop-casen (vi er i `else`-grenen), og vi ekskluderer kanalen fra sættet, er dette korrekt.

**OBS check:** Verificér at `_detect_changes()` kaldes FØR `self._status_cache[ch] = new_state` i update-flowet. Søg i `state_service.py` efter kaldet til `_detect_changes` og bekræft rækkefølgen. Hvis det IKKE er tilfældet, skal active_recording beregningen justeres.

---

### Step 1.6: Tilføj query handler

**Fil:** `app/domains/ingest_monitor/query_handlers.py`

Tilføj import øverst:
```python
from app.core.cqrs.shared_queries import GetCurrentFilenameQuery, GetIngestConnectionStatusQuery, GetRecordingSessionTimeQuery
from .session_tracker import RecordingSessionTracker
```
(Udvid den eksisterende import af `GetCurrentFilenameQuery, GetIngestConnectionStatusQuery` med `GetRecordingSessionTimeQuery`)

Tilføj ny handler-klasse i bunden af filen:

```python
class GetRecordingSessionTimeQueryHandler(QueryHandler[GetRecordingSessionTimeQuery, Optional[str]]):
    """Handler that returns the canonical session_time for the current/recent recording."""

    def __init__(self, session_tracker: RecordingSessionTracker) -> None:
        self._session_tracker = session_tracker

    async def handle(self, query: GetRecordingSessionTimeQuery) -> Optional[str]:
        return self._session_tracker.get_session_time(query.file_creation_time)
```

---

### Step 1.7: Registrér query handler

**Fil:** `app/domains/ingest_monitor/registration.py`

**1) Tilføj imports:**

Udvid shared_queries importen:
```python
from app.core.cqrs.shared_queries import GetCurrentFilenameQuery, GetIngestConnectionStatusQuery, GetRecordingSessionTimeQuery
```

Udvid query_handlers importen:
```python
from .query_handlers import (
    GetIngestStatusQueryHandler,
    GetRecordingPathsQueryHandler,
    GetIngestConnectionStatusQueryHandler,
    GetCurrentFilenameQueryHandler,
    GetRecordingSessionTimeQueryHandler,
)
```

Tilføj import af session tracker:
```python
from .session_tracker import RecordingSessionTracker
```

**2) Ændr funktionssignatur:**

Nuværende:
```python
async def register_ingest_monitor_domain(
    command_bus: CommandBus, 
    query_bus: QueryBus, 
    event_bus: DomainEventBus,
    ingest_monitor_worker
) -> None:
```

Ny:
```python
async def register_ingest_monitor_domain(
    command_bus: CommandBus, 
    query_bus: QueryBus, 
    event_bus: DomainEventBus,
    ingest_monitor_worker,
    session_tracker: RecordingSessionTracker | None = None,
) -> None:
```

**3) Registrér handler** (tilføj efter `filename_handler` registreringen):

```python
    # Register recording session query handler
    if session_tracker:
        session_time_handler = GetRecordingSessionTimeQueryHandler(session_tracker)
        query_bus.register(GetRecordingSessionTimeQuery, session_time_handler.handle)
```

---

### Step 1.8: Instantiér SessionTracker i app startup

**Fil:** Find filen der opretter `IngestStateService` og kalder `register_ingest_monitor_domain()`. Dette er sandsynligvis i `app/main.py` eller `app/dependencies/`.

Søg efter `IngestStateService(` og `register_ingest_monitor_domain(` for at finde de præcise lokationer.

**Ændringer:**

1. Opret `RecordingSessionTracker` med config-værdier:
```python
from app.domains.ingest_monitor.session_tracker import RecordingSessionTracker

session_tracker = RecordingSessionTracker(
    grace_period_seconds=settings.recording_session_grace_period_seconds,
    history_minutes=settings.recording_session_history_minutes,
)
```

2. Pass til `IngestStateService`:
```python
state_service = IngestStateService(
    event_bus=event_bus,
    auto_stop_minutes=settings.justin_auto_stop_minutes,
    auto_stop_warning_minutes=settings.justin_auto_stop_warning_minutes,
    session_tracker=session_tracker,
)
```

3. Pass til `register_ingest_monitor_domain()`:
```python
await register_ingest_monitor_domain(
    command_bus=command_bus,
    query_bus=query_bus,
    event_bus=event_bus,
    ingest_monitor_worker=ingest_monitor_worker,
    session_tracker=session_tracker,
)
```

**VIGTIGT:** Søg i koden efter præcis hvor `IngestStateService` instantieres. Det kan være i `app/dependencies/ingest_monitor.py`, `app/main.py`, eller lignende. Ændr begge kaldsteder.

---

### Step 1.9: Tests for RecordingSessionTracker

**Opret ny fil:** `tests/test_session_tracker.py`

Test-scenarier der SKAL dækkes:

```python
"""Tests for RecordingSessionTracker."""
import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from app.domains.ingest_monitor.session_tracker import (
    RecordingSession,
    RecordingSessionTracker,
)


class TestRecordingSession:
    """Tests for RecordingSession dataclass."""

    def test_is_active_when_no_ended_at(self) -> None:
        session = RecordingSession(
            session_id="test",
            session_time="120530",
            started_at=datetime.now(timezone.utc),
        )
        assert session.is_active is True

    def test_is_not_active_when_ended(self) -> None:
        session = RecordingSession(
            session_id="test",
            session_time="120530",
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
        )
        assert session.is_active is False


class TestRecordingSessionTracker:
    """Tests for RecordingSessionTracker."""

    def _make_tracker(
        self, grace_period: float = 0.1, history_minutes: int = 120
    ) -> RecordingSessionTracker:
        return RecordingSessionTracker(
            grace_period_seconds=grace_period,
            history_minutes=history_minutes,
        )

    def test_first_channel_creates_session(self) -> None:
        tracker = self._make_tracker()
        tracker.handle_channel_started("KAM_1")
        assert tracker.active_session is not None
        assert "KAM_1" in tracker.active_session.channel_names

    def test_second_channel_joins_existing_session(self) -> None:
        tracker = self._make_tracker()
        tracker.handle_channel_started("KAM_1")
        tracker.handle_channel_started("KAM_2")
        assert tracker.active_session is not None
        assert len(tracker.active_session.channel_names) == 2

    def test_all_channels_same_session_time(self) -> None:
        tracker = self._make_tracker()
        tracker.handle_channel_started("KAM_1")
        session_time = tracker.active_session.session_time
        tracker.handle_channel_started("KAM_2")
        tracker.handle_channel_started("KAM_3")
        assert tracker.active_session.session_time == session_time

    @pytest.mark.asyncio
    async def test_session_ends_after_grace_period(self) -> None:
        tracker = self._make_tracker(grace_period=0.05)
        tracker.handle_channel_started("KAM_1")
        tracker.handle_channel_stopped("KAM_1", active_recording_channels=set())
        # Wait for grace period to elapse
        await asyncio.sleep(0.1)
        assert tracker.active_session is None
        assert len(tracker.recent_sessions) == 1

    @pytest.mark.asyncio
    async def test_quick_restart_cancels_grace_period(self) -> None:
        tracker = self._make_tracker(grace_period=1.0)
        tracker.handle_channel_started("KAM_1")
        session_id = tracker.active_session.session_id
        # Stop all channels
        tracker.handle_channel_stopped("KAM_1", active_recording_channels=set())
        # Restart quickly (before grace period)
        tracker.handle_channel_started("KAM_2")
        assert tracker.active_session is not None
        assert tracker.active_session.session_id == session_id  # Same session!

    def test_get_session_time_active(self) -> None:
        tracker = self._make_tracker()
        tracker.handle_channel_started("KAM_1")
        result = tracker.get_session_time()
        assert result is not None
        assert len(result) == 6  # "HHMMSS"

    def test_get_session_time_no_session(self) -> None:
        tracker = self._make_tracker()
        result = tracker.get_session_time()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_time_by_creation_time(self) -> None:
        tracker = self._make_tracker(grace_period=0.05)
        tracker.handle_channel_started("KAM_1")
        session_time = tracker.active_session.session_time
        started_at = tracker.active_session.started_at
        tracker.handle_channel_stopped("KAM_1", active_recording_channels=set())
        await asyncio.sleep(0.1)  # Let session end
        assert tracker.active_session is None

        # File created during the session should match
        file_time = started_at + timedelta(seconds=5)
        result = tracker.get_session_time(file_creation_time=file_time)
        assert result == session_time

    @pytest.mark.asyncio
    async def test_get_session_time_no_match_old_file(self) -> None:
        tracker = self._make_tracker(grace_period=0.05)
        tracker.handle_channel_started("KAM_1")
        tracker.handle_channel_stopped("KAM_1", active_recording_channels=set())
        await asyncio.sleep(0.1)

        # File created way before session → no match
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        result = tracker.get_session_time(file_creation_time=old_time)
        assert result is None

    def test_not_all_channels_stopped(self) -> None:
        """Session should NOT end when only some channels stop."""
        tracker = self._make_tracker()
        tracker.handle_channel_started("KAM_1")
        tracker.handle_channel_started("KAM_2")
        tracker.handle_channel_stopped("KAM_1", active_recording_channels={"KAM_2"})
        # Grace period should NOT have started
        assert tracker._grace_period_task is None
        assert tracker.active_session is not None
```

**Kør:** `pytest tests/test_session_tracker.py -v`

---

## Fase 2: session_time på TrackedFile + QueueJob

### Step 2.1: Tilføj `session_time` felt på TrackedFile

**Fil:** `app/models.py`

Find `retry_info` feltet (sidst i TrackedFile-klassen, før `model_config`). Tilføj **efter** `retry_info`:

```python
    session_time: Optional[str] = Field(
        default=None,
        description="Canonical session time (HHMMSS) from recording session tracker",
    )
```

---

### Step 2.2: Database migration

**Kør kommando:**
```bash
alembic revision --autogenerate -m "add_session_time_to_tracked_files"
```

Verificér at den genererede migration tilføjer `session_time` kolonne. Hvis alembic ikke auto-detekterer det (fordi TrackedFile muligvis ikke er en SQLAlchemy model), opret manuelt:

**Opret fil:** `alembic/versions/XXXX_add_session_time.py` (med korrekt revision ID)

```python
"""add session_time to tracked_files

Revision ID: <generer>
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.add_column("tracked_files", sa.Column("session_time", sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column("tracked_files", "session_time")
```

**NOTE:** Undersøg om TrackedFile er en Pydantic model (in-memory) eller SQLAlchemy model. Hvis Pydantic-only med `InMemoryFileRepository`, behøves **ingen** migration — feltet på TrackedFile er nok. Tjek `app/core/file_repository.py` for storage-typen.

---

### Step 2.3: Tag TrackedFile med session_time ved discovery

**Fil:** `app/domains/file_discovery/file_discovery_slice.py`

**1) Tilføj imports:**
```python
from app.core.cqrs.query_bus import QueryBus
from app.core.cqrs.shared_queries import GetRecordingSessionTimeQuery
```

**2) Ændr constructor:**

Find `__init__()` og tilføj `query_bus` parameter. Nuværende constructor har formentlig:
- `file_repository`
- `event_bus`
- Muligvis `state_machine`

Tilføj `query_bus: QueryBus | None = None` parameter og gem som `self._query_bus = query_bus`.

**3) Ændr `add_discovered_file()` metode:**

Find denne sektion i `add_discovered_file()`:
```python
    # Create new tracked file
    tracked_file = TrackedFile(
        file_path=file_path,
        file_size=file_size,
        last_write_time=last_write_time,
        creation_time=creation_time,
        status=FileStatus.DISCOVERED,
    )
```

Ændr til:
```python
    # Query session time from ingest_monitor (if available)
    session_time: str | None = None
    if self._query_bus:
        try:
            session_time = await self._query_bus.execute(
                GetRecordingSessionTimeQuery(file_creation_time=creation_time)
            )
        except Exception:
            logging.debug("Could not query session time — no handler registered")

    # Create new tracked file
    tracked_file = TrackedFile(
        file_path=file_path,
        file_size=file_size,
        last_write_time=last_write_time,
        creation_time=creation_time,
        status=FileStatus.DISCOVERED,
        session_time=session_time,
    )
```

**4) Opdater instantiering:**

Søg efter hvor `FileDiscoverySlice` instantieres (sandsynligvis i `app/domains/file_discovery/registration.py` eller `app/dependencies/file_discovery.py`). Tilføj `query_bus=query_bus` til constructor-kaldet.

**VIGTIGT:** `file_discovery` importerer KUN fra `app/core/` (QueryBus, shared_queries). Den importerer IKKE fra `ingest_monitor`. ✅ Arkitektur OK.

---

### Step 2.4: Tilføj `session_time` på QueueJob

**Fil:** `app/domains/file_processing/consumer/job_models.py`

Find `QueueJob` dataclass. Tilføj felt **efter** `last_error_message`:

```python
    session_time: Optional[str] = None
```

Tilføj import øverst:
```python
from typing import Optional
```
(Sandsynligvis allerede importeret — tjek.)

---

### Step 2.5: Propagér session_time fra TrackedFile til QueueJob

**Fil:** `app/domains/file_processing/command_handlers.py`

I `QueueFileCommandHandler.handle()`, find hvor `QueueJob` oprettes:

```python
            job = QueueJob(
                file_id=tracked_file.id,
                file_path=tracked_file.file_path,
                file_size=tracked_file.file_size,
                creation_time=tracked_file.creation_time,
                is_growing_at_queue_time=is_growing,
                added_to_queue_at=datetime.now(timezone.utc),
                retry_count=0,
            )
```

Ændr til:
```python
            job = QueueJob(
                file_id=tracked_file.id,
                file_path=tracked_file.file_path,
                file_size=tracked_file.file_size,
                creation_time=tracked_file.creation_time,
                is_growing_at_queue_time=is_growing,
                added_to_queue_at=datetime.now(timezone.utc),
                retry_count=0,
                session_time=tracked_file.session_time,
            )
```

---

## Fase 3: Template Engine udvidelse

### Step 3.1: Tilføj `extra_vars` til template engine

**Fil:** `app/domains/file_processing/output_folder_template.py`

**1) Ændr `generate_output_path()` signatur og body:**

Nuværende:
```python
    def generate_output_path(self, filename: str, source_path: str = "") -> str:
```

Ny:
```python
    def generate_output_path(self, filename: str, source_path: str = "", extra_vars: dict[str, str] | None = None) -> str:
```

**2) Ændr variabel-extraction i `generate_output_path()`:**

Find:
```python
        # Extract variables for substitution
        variables = self._extract_variables(filename)
```

Ændr til:
```python
        # Extract variables for substitution
        variables = self._extract_variables(filename)

        # Merge extra variables (e.g. session_time from recording session)
        if extra_vars:
            variables.update(extra_vars)
```

**VIGTIGT:** `extra_vars` overskriver standard-variabler hvis der er navnekollision. Det er ønsket adfærd for `{session_time}`. Variabler der IKKE er i en template ignoreres stille.

---

### Step 3.2: Opdater `build_destination_path_with_template()`

**Fil:** `app/utils/file_operations.py`

Nuværende:
```python
def build_destination_path_with_template(
    source_path: Path, source_base: Path, dest_base: Path, template_engine=None
) -> Path:
    filename = source_path.name

    # Use template engine if available and enabled
    if template_engine and template_engine.is_enabled():
        return Path(template_engine.generate_output_path(filename))

    # Fall back to standard path preservation
    return build_destination_path(source_path, source_base, dest_base)
```

Ny:
```python
def build_destination_path_with_template(
    source_path: Path, source_base: Path, dest_base: Path, template_engine=None,
    extra_vars: dict[str, str] | None = None,
) -> Path:
    filename = source_path.name

    # Use template engine if available and enabled
    if template_engine and template_engine.is_enabled():
        return Path(template_engine.generate_output_path(filename, extra_vars=extra_vars))

    # Fall back to standard path preservation
    return build_destination_path(source_path, source_base, dest_base)
```

---

### Step 3.3: Opdater JobFilePreparationService

**Fil:** `app/domains/file_processing/consumer/job_file_preparation_service.py`

**1) Ændr `_calculate_destination_path()`:**

Nuværende signatur og kald varierer — find metoden. Den tager formentlig `file_path: str`. Tilføj `session_time: str | None = None` parameter.

Ændr call:
```python
    async def _calculate_destination_path(self, file_path: str, session_time: str | None = None) -> Path:
        """Calculate destination path using template engine if enabled."""
        source = Path(file_path)
        source_base = Path(self.settings.source_directory)
        dest_base = Path(self.settings.destination_directory)

        extra_vars: dict[str, str] = {}
        if session_time:
            extra_vars["session_time"] = session_time

        dest_path = build_destination_path_with_template(
            source, source_base, dest_base, self.template_engine,
            extra_vars=extra_vars,
        )

        return await generate_conflict_free_path(Path(dest_path))
```

**2) Opdater kaldet til `_calculate_destination_path()`:**

Søg efter hvor `_calculate_destination_path(file_path)` kaldes. Det er sandsynligvis i `prepare()` eller `prepare_job()` metoden. Tilføj `session_time=job.session_time` (eller hvad parameteren hedder i konteksten).

Eksempel:
```python
# Nuværende:
dest_path = await self._calculate_destination_path(job.file_path)

# Ny:
dest_path = await self._calculate_destination_path(job.file_path, session_time=job.session_time)
```

**VIGTIGT:** Tjek præcis hvad kaldet ser ud — `job` er et `QueueJob` objekt der nu har `session_time`.

---

## Fase 4: Verifikation

### Step 4.1: Kør quality gate

```bash
# Alle tests
pytest --ignore=scripts

# Type checking
mypy app/

# Arkitektur-kontrakter
lint-imports
```

**ALLE SKAL BESTÅ.** Hvis noget fejler, fix det i samme PR.

### Step 4.2: Test-scenarier at verificere

| # | Scenario | Forventet |
|---|----------|-----------|
| 1 | 8 kanaler starter, filer discovers under session | Alle får samme `session_time` |
| 2 | Audio .wav filer discovers under session | Får samme `session_time` som .mxf |
| 3 | Template `{session_time}` med aktiv session | Alle filer i samme mappe |
| 4 | Template `{time}` (gammel config) | Uændret adfærd, ingen regression |
| 5 | Justin offline, filer discovers | `session_time` = None, `{time}` bruges |
| 6 | Hurtig stop/start inden 5s | Samme session fortsætter |
| 7 | Stop, vent > 5s, start | Ny session oprettes |
| 8 | Fil discovers efter session slut (within 60s margin) | Matcher seneste session |
| 9 | Service restart under optagelse | Nye filer har session_time=None (fallback) |

---

## Berørte filer (komplet)

### Nye filer
| Fil | Formål |
|-----|--------|
| `app/domains/ingest_monitor/session_tracker.py` | RecordingSessionTracker + RecordingSession |
| `tests/test_session_tracker.py` | Unit tests |
| `alembic/versions/XXXX_add_session_time.py` | Migration (kun hvis SQLAlchemy) |

### Modificerede filer
| Fil | Ændring |
|-----|---------|
| `app/config.py` | Nye settings: grace_period, history_minutes |
| `app/core/events/ingest_events.py` | Nye events: RecordingSessionStarted/Ended |
| `app/core/cqrs/shared_queries.py` | Ny query: GetRecordingSessionTimeQuery |
| `app/models.py` | Nyt felt: TrackedFile.session_time |
| `app/domains/ingest_monitor/state_service.py` | Wire SessionTracker i __init__ og _detect_changes |
| `app/domains/ingest_monitor/query_handlers.py` | Ny handler: GetRecordingSessionTimeQueryHandler |
| `app/domains/ingest_monitor/registration.py` | Registrér ny query handler |
| `app/domains/file_discovery/file_discovery_slice.py` | Query session_time, tag TrackedFile |
| `app/domains/file_processing/consumer/job_models.py` | Nyt felt: QueueJob.session_time |
| `app/domains/file_processing/command_handlers.py` | Propagér session_time til QueueJob |
| `app/domains/file_processing/output_folder_template.py` | extra_vars parameter på generate_output_path |
| `app/utils/file_operations.py` | extra_vars parameter på build_destination_path_with_template |
| `app/domains/file_processing/consumer/job_file_preparation_service.py` | Byg extra_vars, pass session_time |
| `app/main.py` ELLER `app/dependencies/ingest_monitor.py` | Instantiér SessionTracker, wire til service + registration |
| `app/dependencies/file_discovery.py` ELLER tilsvarende | Pass query_bus til FileDiscoverySlice |

### Filer der IKKE skal ændres
- `app/core/file_state_machine.py` — ingen ændring
- `app/core/file_repository.py` — ingen ændring (session_time er bare et felt på TrackedFile)
- `app/domains/audio_recording/` — ingen ændring (audio filer discovers automatisk via pipeline)

---

## Beslutninger

| Beslutning | Valg | Begrundelse |
|------------|------|-------------|
| Hvor lever session-konceptet? | `ingest_monitor` | Domænet der kender optagelses-livscyklen |
| Grace period | 5s (konfigurerbar) | Forhindrer accidentielle nye sessions |
| Storage | In-memory | TrackedFile.session_time er persistent; sessions selv behøver ikke overleve restart |
| `{session_time}` activation | Opt-in via template config | Bruger ændrer template fra `{time}` til `{session_time}` |
| Fallback ved None session_time | `{session_time}` substitueres ikke (forbliver literal) | Bruger kan have fallback-rule. Alternativ: fald tilbage til `{time}` — besluttes under implementation |
| Cross-domain kommunikation | QueryBus | Arkitektur-konform, ingen direkte imports |
| Audio filer | Automatisk | Scanner accepterer .wav, pipeline kopierer, session_time tagges |
| Session events | Tilføjes (optional) | Nyttige for audio recorder i fremtiden |
