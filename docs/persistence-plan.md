# Persistence Plan — SQLite for File Transfer Agent

**Dato:** 2026-03-30  
**Status:** Plan godkendt, implementering ikke startet  
**Kontekst:** Systemet har 750 tests, 73% coverage, 12 sikkerhedsrettelser. Næste step er persistence.

---

## TL;DR

Tilføj SQLite persistence i 3 faser:
1. **FileRepository → SQLite** — filer overlever genstart
2. **Event-log persistence** — System Events overlever genstart
3. **User settings i DB + UI** — erstat env-filer for ~10 brugervendte settings

**Teknologivalg:** `aiosqlite` direkte (ingen ORM) + `Alembic` migrations + WAL mode.  
**Arkitekturen bevares** — Repository-interface er uændret, domæner mærker intet.

---

## Fase 1: FileRepository → SQLite (Hovedprioritet)

### Arkitektur-beslutning
- **Ny fil:** `app/core/sqlite_file_repository.py` implementerer **præcis** samme interface som nuværende `FileRepository`
- **Bevares uændret:** `FileStateMachine`, alle domæner, CQRS handlers
- **Protocol:** Tilføj `FileRepositoryProtocol` i `app/core/protocols.py` så begge implementeringer er typecheck-bare
- **Database fil:** `data/file-agent.db` (konfigurbar via `Settings.database_path`)
- **In-memory bevares:** `FileRepository` bruges fortsat til tests og som fallback

### Steps

| # | Step | Depends on | Status |
|---|------|------------|--------|
| 1.1 | **Alembic setup** — installer `aiosqlite` + `alembic`, opret `alembic/` med config, initial migration: `tracked_files` tabel | — | ⬜ |
| 1.2 | **FileRepositoryProtocol** — `app/core/protocols.py` med Protocol for de 7 repository-metoder | — | ⬜ |
| 1.3 | **SqliteFileRepository** — `app/core/sqlite_file_repository.py` med ren SQL, WAL mode, JSON for `retry_info` | 1.1 | ⬜ |
| 1.4 | **DB init i lifespan** — `await sqlite_repo.init_db()` i `main.py`, `Settings.database_path` | 1.3 | ⬜ |
| 1.5 | **Swap i dependencies.py** — `get_file_repository()` returnerer `SqliteFileRepository` | 1.3 | ⬜ |
| 1.6 | **Tests** — 1:1 test-suite for sqlite repo (`:memory:`), verificer alle 750+ tests bestået | 1.3 | ⬜ |

### Step 1.1: Alembic setup (detaljer)
- Tilføj `aiosqlite` + `alembic` til `requirements.txt`
- Opret `alembic.ini` i projekt-rod
- Opret `alembic/env.py` konfigureret til SQLite
- Initial migration: `tracked_files` tabel med alle `TrackedFile`-felter som kolonner
- `retry_info` gemmes som JSON-kolonne (serialiseret `RetryInfo`)
- Indexes: `file_path`, `status`, `discovered_at`, `completed_at`
- Tilføj `data/` til `.gitignore`

**Schema:**
```sql
CREATE TABLE tracked_files (
    id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    file_size INTEGER NOT NULL DEFAULT 0,
    destination_path TEXT,
    copy_progress REAL NOT NULL DEFAULT 0.0,
    bytes_copied INTEGER NOT NULL DEFAULT 0,
    copy_speed_mbps REAL NOT NULL DEFAULT 0.0,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    retry_info TEXT,  -- JSON serialized RetryInfo
    discovered_at TEXT NOT NULL,  -- ISO datetime
    creation_time TEXT,
    last_write_time TEXT,
    started_copying_at TEXT,
    completed_at TEXT,
    failed_at TEXT,
    space_error_at TEXT,
    last_growth_check TEXT,
    growth_rate_mbps REAL NOT NULL DEFAULT 0.0,
    previous_file_size INTEGER NOT NULL DEFAULT 0,
    first_seen_size INTEGER NOT NULL DEFAULT 0,
    growth_stable_since TEXT
);

CREATE INDEX ix_tracked_files_file_path ON tracked_files(file_path);
CREATE INDEX ix_tracked_files_status ON tracked_files(status);
CREATE INDEX ix_tracked_files_discovered_at ON tracked_files(discovered_at);
CREATE INDEX ix_tracked_files_completed_at ON tracked_files(completed_at);
```

### Step 1.2: FileRepositoryProtocol (detaljer)
```python
# app/core/protocols.py
from typing import Protocol, Optional, List, Set
from datetime import datetime
from app.models import TrackedFile, FileStatus

class FileRepositoryProtocol(Protocol):
    async def get_by_id(self, file_id: str) -> Optional[TrackedFile]: ...
    async def get_all(self) -> List[TrackedFile]: ...
    async def add(self, tracked_file: TrackedFile) -> None: ...
    async def update(self, tracked_file: TrackedFile) -> None: ...
    async def remove(self, file_id: str) -> bool: ...
    async def count(self) -> int: ...
    async def prune_terminal_files(self, terminal_states: Set[FileStatus], cutoff_date: datetime) -> int: ...
```

### Step 1.3: SqliteFileRepository (detaljer)
- `__init__(db_path: str)` — gemmer path, connection oprettes i `init_db()`
- `async init_db()` — kører Alembic migrations programmatisk, aktiverer WAL mode
- Alle skrive-operationer bruger `BEGIN IMMEDIATE` transactions
- `_to_tracked_file(row: sqlite3.Row) -> TrackedFile` — mapper DB-row til Pydantic model
- `_to_row(tracked_file: TrackedFile) -> dict` — mapper Pydantic model til dict for INSERT/UPDATE
- `retry_info`: `json.dumps(retry_info.model_dump())` ved write, `RetryInfo(**json.loads(data))` ved read
- Datetimes gemmes som ISO 8601 strings

### Step 1.4: DB init i lifespan (detaljer)
- Tilføj `database_path: str = "data/file-agent.db"` i `app/config.py`
- I `main.py` lifespan, **før alt andet**:
  ```python
  sqlite_repo = get_file_repository()
  await sqlite_repo.init_db()
  ```
- Ved shutdown: `await sqlite_repo.close()`

### Step 1.5: Swap i dependencies.py (detaljer)
- `get_file_repository()` ændres til at oprette `SqliteFileRepository(settings.database_path)`
- `FileStateMachine` typehint ændres fra `FileRepository` til `FileRepositoryProtocol`
- Ingen andre ændringer nødvendige — alle domæner bruger allerede repository via DI

### Step 1.6: Tests (detaljer)
- Ny testfil: `tests/core/test_sqlite_file_repository.py`
- Brug `aiosqlite` med `:memory:` for hastighed
- 1:1 test af alle 7 repository-metoder
- Edge cases: concurrent writes, prune med mixed states, retry_info serialization
- Tilføj `conftest.py` fixture: `@pytest.fixture` der swapper singleton til in-memory SQLite
- Verificer: `python -m pytest tests/ -x -q` → alle 750+ tests bestået

### Berørte filer
| Fil | Ændring |
|-----|---------|
| `requirements.txt` | Tilføj `aiosqlite`, `alembic` |
| `alembic.ini` | NY — Alembic config |
| `alembic/env.py` | NY — migration environment |
| `alembic/versions/001_tracked_files.py` | NY — initial migration |
| `app/core/protocols.py` | NY — FileRepositoryProtocol |
| `app/core/sqlite_file_repository.py` | NY — SQLite implementation |
| `app/core/file_repository.py` | Uændret (bevares som fallback) |
| `app/core/file_state_machine.py` | Typehint: `FileRepository` → `FileRepositoryProtocol` |
| `app/config.py` | Tilføj `database_path` setting |
| `app/dependencies.py` | Swap `get_file_repository()` implementation |
| `app/main.py` | Tilføj `init_db()` + `close()` i lifespan |
| `tests/core/test_sqlite_file_repository.py` | NY — SQLite repo tests |
| `tests/conftest.py` | Tilføj in-memory DB fixture |
| `.gitignore` | Tilføj `data/` |

### Verification
- [ ] `python -m pytest tests/ -x -q` → alle 750+ tests bestået
- [ ] Stop → genstart app → filer overlever i UI
- [ ] Manuel test: kopier en fil, genstart, filen er stadig synlig med korrekt status
- [ ] `alembic upgrade head` kører uden fejl på fresh DB
- [ ] Performance: 1000 filer i DB, UI-opdatering < 100ms

---

## Fase 2: Event-log Persistence

### Formål
System Events i UI (`GlobalEventLogger`) overlever genstart. Brugeren kan se historik.

### Arkitektur-beslutning
- **Hybrid model:** SQLite for persistens + in-memory deque som read-cache
- **Write-through:** hvert event skrives til BÅDE deque (hurtig UI) OG SQLite (persistens)
- **Ved opstart:** fyld deque fra SQLite (sidste 200 events)
- **Auto-pruning:** slet events ældre end 30 dage

### Steps

| # | Step | Depends on | Status |
|---|------|------------|--------|
| 2.1 | **Alembic migration: `system_events` tabel** | Fase 1.1 | ⬜ |
| 2.2 | **SqliteEventStore** — `app/core/sqlite_event_store.py` | 2.1 | ⬜ |
| 2.3 | **Swap i GlobalEventLogger** — write-through + startup rehydration | 2.2 | ⬜ |
| 2.4 | **Events API udvidelse** — `?limit=500`, `?from_date=...` | 2.3 | ⬜ |

### Step 2.1: Schema
```sql
CREATE TABLE system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,  -- ISO datetime
    event_type TEXT NOT NULL,
    level TEXT NOT NULL,       -- INFO, WARNING, ERROR
    message TEXT NOT NULL,
    context TEXT               -- JSON
);

CREATE INDEX ix_system_events_timestamp ON system_events(timestamp);
CREATE INDEX ix_system_events_level ON system_events(level);
CREATE INDEX ix_system_events_event_type ON system_events(event_type);
```

### Step 2.2: SqliteEventStore (detaljer)
- Deler database-connection med `SqliteFileRepository` (samme `file-agent.db`)
- `async add_event(logged_event: LoggedEvent)` → INSERT
- `async get_events(limit, level?, from_date?)` → SELECT med filtre
- `async prune_old_events(days: int = 30)` → DELETE WHERE timestamp < cutoff
- Prune køres automatisk ved opstart og periodisk (via LifecycleService)

### Step 2.3: GlobalEventLogger swap (detaljer)
- Constructor: `__init__(max_size=200, event_store: Optional[SqliteEventStore] = None)`
- `_log_event()`: skriv til deque + `await event_store.add_event()` (if available)
- `get_all_logs(limit)`: hvis limit ≤ 200 → deque, ellers → SQLite
- Opstart: `await _rehydrate_from_db()` — fyld deque med de nyeste 200 events fra DB

### Step 2.4: Events API (detaljer)
- `GET /api/events/?limit=500` — fungerer nu med >200 events
- `GET /api/events/?from_date=2026-03-01` — ny parameter
- Eksisterende endpoint-kontrakt bevares (bagudkompatibel)

### Berørte filer
| Fil | Ændring |
|-----|---------|
| `alembic/versions/002_system_events.py` | NY — events migration |
| `app/core/sqlite_event_store.py` | NY — event persistence |
| `app/core/global_event_logger.py` | Tilføj SQLite backing |
| `app/dependencies.py` | Wire event store til logger |
| `app/domains/shared/api/events_api.py` | Udvid med dato-filter |
| `tests/core/test_sqlite_event_store.py` | NY — event store tests |

### Verification
- [ ] Tilføj events, genstart, events vises stadig i UI
- [ ] `GET /api/events/?limit=500` returnerer events fra DB
- [ ] `GET /api/events/?from_date=2026-03-28` returnerer filtrerede events
- [ ] Auto-pruning fjerner events ældre end 30 dage
- [ ] Alle 750+ tests bestået

---

## Fase 3: User Settings i DB + UI

### Formål
Erstat env-filer for de ~10 brugervendte indstillinger. UI-side erstatter nuværende read-only settings-visning.

### Arkitektur-beslutning
- **Prioritet:** hardcoded defaults → env-fil → DB (højest prioritet)
- **Kun ~10 settings** flyttes til DB — resten beholer fornuftige defaults i koden
- Env-fil bevares for infrastruktur-settings (log_level, API URLs, etc.)
- **Migration:** ved første opstart læses env-fil → skrives til DB → herefter har DB forrang

### Settings der flyttes til DB

| Setting | Type | Default | Kræver genstart |
|---------|------|---------|-----------------|
| `source_directory` | str | (påkrævet) | ✅ Ja |
| `destination_directory` | str | (påkrævet) | ✅ Ja |
| `tally_light_switch_ip` | str | `""` | ✅ Ja |
| `enable_auto_mount` | bool | `false` | ✅ Ja |
| `network_share_url` | str | `""` | ✅ Ja |
| `macos_mount_point` | str | `""` | ✅ Ja |
| `output_folder_template_enabled` | bool | `false` | ❌ Nej |
| `output_folder_rules` | str | `""` | ❌ Nej |
| `output_folder_default_category` | str | `"default"` | ❌ Nej |
| `output_folder_date_format` | str | `"filename[0:6]"` | ❌ Nej |

### Steps

| # | Step | Depends on | Status |
|---|------|------------|--------|
| 3.1 | **Alembic migration: `user_settings` tabel** | Fase 1.1 | ⬜ |
| 3.2 | **SettingsService** — loader med 3-lags prioritet | 3.1 | ⬜ |
| 3.3 | **CQRS:** `UpdateUserSettingCommand` + `GetUserSettingsQuery` | 3.2 | ⬜ |
| 3.4 | **REST API:** `GET/PUT /api/system/user-settings` | 3.3 | ⬜ |
| 3.5 | **UI formular** — erstatter nuværende read-only settings-side | 3.4 | ⬜ |
| 3.6 | **Env-fil migration** — env → DB ved første opstart | 3.2 | ⬜ |

### Step 3.1: Schema
```sql
CREATE TABLE user_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,  -- JSON-encoded value
    updated_at TEXT NOT NULL  -- ISO datetime
);
```

### Step 3.2: SettingsService (detaljer)
- `app/domains/shared/settings_service.py`
- Constructor: `__init__(db_path: str, defaults: dict, env_overrides: dict)`
- Loading order: `defaults` → `env_overrides` → DB (DB vinder)
- `async get(key: str) -> Any` — returnerer merged value
- `async set(key: str, value: Any)` — validér + gem i DB + invalidér cache
- `async get_all_user_settings() -> dict` — alle ~10 settings med current values
- Validering via Pydantic model (`UserSettingsModel`) for type + range checks
- In-memory cache dict, invalideres ved `set()`

### Step 3.3: Settings CQRS (detaljer)
- `UpdateUserSettingCommand(key: str, value: Any)` → handler gemmer i DB
- `GetUserSettingsQuery()` → handler returnerer alle bruger-settings
- Registrering i `app/domains/shared/registration.py`

### Step 3.4: REST API (detaljer)
- `GET /api/system/user-settings` → returnerer `{settings: [...], requires_restart: bool}`
- `PUT /api/system/user-settings` → body: `{key: value, ...}`, validér, gem
- Response inkluderer `requires_restart: true` hvis source/dest/mount ændres
- Erstatter/udvider nuværende `GET /api/system/settings` endpoint

### Step 3.5: UI (detaljer)
- Erstat nuværende read-only settings-side med formularer
- Input felter for stier (source, destination)
- Toggles for booleans (auto-mount, output-folder)
- Textarea for output-folder regler
- Save-knap → `PUT /api/system/user-settings`
- "Restart required" badge vises når pending ændringer kræver genstart
- "Restart now" knap (bruger eksisterende restart-endpoint)

### Step 3.6: Env-fil migration (detaljer)
- Ved opstart: tjek om DB `user_settings` er tom
- Hvis tom: læs de ~10 settings fra nuværende `Settings` (som stammer fra env-fil)
- Skriv til DB → log `"Migrated 10 settings from env to database"`
- Herefter ignoreres env-fil for de ~10 settings
- Env-fil bevares og virker stadig som fallback for nye installationer

### Berørte filer
| Fil | Ændring |
|-----|---------|
| `alembic/versions/003_user_settings.py` | NY — settings migration |
| `app/domains/shared/settings_service.py` | NY — settings service |
| `app/domains/shared/commands.py` | Tilføj `UpdateUserSettingCommand` |
| `app/domains/shared/queries.py` | Tilføj `GetUserSettingsQuery` |
| `app/domains/shared/registration.py` | Registrer nye handlers |
| `app/domains/shared/api/config_api.py` | Udvid med `GET/PUT /api/system/user-settings` |
| `app/config.py` | Ændr Settings loader til at merge med DB |
| `app/domains/presentation/static/` | UI ændringer (settings-formular) |
| `app/domains/presentation/templates/` | Settings-form template |
| `tests/domains/test_settings_service.py` | NY — settings service tests |

### Verification
- [ ] Ændr `source_directory` i UI → genstart → ny sti bruges
- [ ] Ændr `output_folder_rules` i UI → virker umiddelbart (ingen genstart)
- [ ] Fresh install: DB tom, defaults bruges, bruger konfigurerer via UI
- [ ] Migration: eksisterende env-fil værdier overføres til DB ved opstart
- [ ] Alle 750+ tests bestået

---

## Teknologivalg & Begrundelse

| Beslutning | Valg | Begrundelse |
|-----------|------|-------------|
| ORM | **aiosqlite direkte** (ingen ORM) | Lettere, ingen ekstra dependency chain, fuld SQL-kontrol |
| Migrations | **Alembic fra start** | Schema-evolution er kritisk for produktion |
| Journal mode | **WAL** | Tillader concurrent reads under write |
| Database | **SQLite** (ikke PostgreSQL) | Single-instance service, intet behov for distributed DB |
| Event caching | **DB + deque hybrid** | Hurtig UI (<100ms) + persistens |
| Settings prioritet | **defaults → env → DB** | Bagudkompatibel, DB vinder |

---

## Scope

### Inkluderet
- FileRepository persistence (filer overlever genstart)
- Event log persistence (System Events overlever genstart)
- User settings i DB med UI (~10 settings)
- Alembic migrations (schema-evolution)

### Eksplicit ekskluderet
- PostgreSQL support
- Multi-instance / distributed deployment
- Fuld config-profil system
- IngestMonitor state persistence (kanal-cache er transient by design)
- Real-time settings hot-reload for settings der kræver genstart

---

## Risici & Overvejelser

| Risiko | Mitigering |
|--------|------------|
| **SQLite single-writer bottleneck** | WAL mode + `BEGIN IMMEDIATE`. For denne single-instance service med ~10 writes/sec er det rigeligt |
| **DB-fil corruption ved strømsvigt** | WAL mode + SQLite's built-in journaling. Overvej `PRAGMA synchronous=NORMAL` (default) |
| **Backup** | DB-filen bør inkluderes i backup. Overvej periodic `.backup` API-endpoint |
| **DB-filplacering for PyInstaller/macOS** | `database_path` er konfigurerbar. PyInstaller-build skal pege på writeable lokation |
| **Migration fejl i produktion** | Alembic giver rollback-mulighed. Test migrations grundigt |
| **Test-isolation** | `:memory:` SQLite i tests. `reset_singletons()` nulstiller som nu |
