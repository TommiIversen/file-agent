# Production Readiness Review — File Transfer Agent

**Dato:** 2026-03-28  
**Reviewer:** GitHub Copilot  
**Kontekst:** Systemet skal i produktion i DR. Denne gennemgang dækker arkitektur, kodekvalitet og sikkerhed.  
**Test-status:** 750 tests, 73% coverage (se `docs/test-coverage-plan.md`)  
**Rettelser udført:** 2026-03-28 — alle 12 tiltag implementeret, 750/750 tests bestået.

---

## Samlet Vurdering

| Område | Score | Status |
|--------|-------|--------|
| Arkitektur & Domænedesign | ⭐⭐⭐⭐⭐ | Excellent |
| State Machine & CQRS | ⭐⭐⭐⭐⭐ | Excellent |
| Error isolation (EventBus) | ⭐⭐⭐⭐⭐ | Excellent |
| Kopierings-pipeline (IO loop + growing copy) | ⭐⭐⭐⭐⭐ | Excellent |
| Dependency pinning | ⭐⭐⭐⭐⭐ | Excellent |
| Graceful shutdown | ⭐⭐⭐⭐ | God, men mangler timeout |
| Fejlhåndtering & logging | ⭐⭐⭐⭐ | Rettet — exc_info=True tilføjet |
| Sikkerhed | ⭐⭐⭐⭐ | Rettet — alle fund adresseret |

**Anbefaling:** ~~Fix de 4 kritiske sikkerhedsfund + de 3 høj-prioritet issues inden deploy.~~ **Alle 12 tiltag er implementeret.** Eneste resterende risiko er in-memory FileRepository (datatab ved genstart) — se SQLite-anbefaling.

---

## Del 1: High-Level Review

### 1.1 Arkitektur — Hvad der fungerer rigtig godt

Systemets overordnede arkitektur er **bemærkelsesværdigt velbygdt** for et projekt af denne størrelse:

- **CQRS med CommandBus/QueryBus:** Giver ren adskillelse mellem læse- og skriveoperationer. Registrering sker per domæne via `registration.py`, hvilket gør det nemt at forstå hvad hvert domæne tilbyder.

- **DomainEventBus med fejl-isolation:** Hvert event-subscriber er wrapped i `try/except` (`app/core/events/event_bus.py` linje 75-80), så én fejlende subscriber aldrig blokerer andre. Det er præcis det rigtige pattern for et system der kører 24/7.

- **FileStateMachine med lock-baseret atomicitet:** `app/core/file_state_machine.py` bruger `asyncio.Lock` til at garantere READ→VALIDATE→MODIFY→SAVE sker atomisk. Events publiceres *udenfor* lock'en for at undgå deadlocks. Velovervejet design.

- **Vertikal slice-arkitektur:** Hvert domæne (`file_discovery`, `file_processing`, `storage`, `ingest_monitor`, `tally_light`, `presentation`) er selvstændigt med egne commands, queries, handlers og API-endpoints.

- **SRP i storage_monitor:** De 4 sub-klasser (`StorageState`, `DirectoryManager`, `NotificationHandler`, `MountStatusBroadcaster`) viser god nedbrydning af et komplekst domæne.

### 1.2 Arkitektur — Hvad der kan forbedres

#### A. In-memory FileRepository = datatab ved genstart

**Fil:** `app/core/file_repository.py`  
**Risiko:** Høj

Al fil-tracking data lever i en `Dict[str, TrackedFile]`. Ved genstart mistes:
- Historik over kopierede filer
- Filer der var undervejs i kopiering
- Status for alle filer i UI

**Anbefaling:** SQLite-persistence (allerede planlagt i `docs/Refaktoriseringsplan.md`). Prioriter dette *efter* sikkerhedsrettelser men *før* DR stoler på systemet som eneste fil-tracking.

#### B. Fire-and-forget events kan mistes

**Filer:** 5 steder i kodebasen

| Fil | Linje | Kontekst |
|-----|-------|----------|
| `app/core/file_state_machine.py` | 204 | Status-ændring event |
| `app/domains/file_processing/copy/growing_copy.py` | 392 | Progress event |
| `app/domains/file_processing/copy/copy_io_loop.py` | 203 | Progress event |
| `app/domains/file_processing/copy/network_error_detector.py` | 104 | Netværksfejl event |
| `app/domains/shared/config_handlers.py` | 122 | Restart delay |

Mønsteret er:
```python
asyncio.create_task(self._event_bus.publish(event))  # Ingen reference gemt
```

Tasken kan garbage-collectes eller mistes ved crash. For progress-events er det acceptabelt, men for `FileStatusChangedEvent` (linje 204 i state machine) kan det betyde at UI'et aldrig opdateres.

**Anbefaling:** Gem task-referencer i en `set()` og brug `task.add_done_callback(task_set.discard)` patterntet — Python's officielle anbefaling for fire-and-forget tasks:
```python
_pending_events: set[asyncio.Task] = set()

task = asyncio.create_task(self._event_bus.publish(event))
_pending_events.add(task)
task.add_done_callback(_pending_events.discard)
```

#### C. Shutdown mangler timeout

**Fil:** `app/main.py` linje 213-216

```python
for task in _background_tasks:
    task.cancel()
if _background_tasks:
    await asyncio.gather(*_background_tasks, return_exceptions=True)
```

Hvis en task hænger (f.eks. netværks-timeout under kopiering), hænger hele shutdown.

**Anbefaling:** Wrap i `asyncio.wait_for` med 30-sekunders timeout:
```python
try:
    await asyncio.wait_for(
        asyncio.gather(*_background_tasks, return_exceptions=True),
        timeout=30.0
    )
except asyncio.TimeoutError:
    logging.error("Shutdown timeout after 30s — forcing exit")
```

#### D. TallyLight shutdown er betinget

**Fil:** `app/main.py` linje 209-211

```python
if 'tally_handler' in locals() and hasattr(tally_handler, 'shutdown'):
    await tally_handler.shutdown()
```

`tally_handler` er defineret på linje 99, så den vil altid være i scope, men mønsteret er skrøbeligt — en refaktorering af startup-rækkefølgen kan bryde det.

**Anbefaling:** Brug en eksplicit None-check i stedet:
```python
if tally_handler is not None:
    await tally_handler.shutdown()
```

#### E. `_singletons`-dict eksponeres direkte fra dependencies

**Fil:** `app/main.py` linje 87

```python
from app.dependencies import _singletons
_singletons["network_coordinator"] = network_services["network_coordinator"]
```

`main.py` rækker ind i dependencies' interne state. Det er en afhængigheds-inversion i den forkerte retning.

**Anbefaling:** Tilføj en `register_network_coordinator(coordinator)` funktion til `dependencies.py` i stedet.

---

## Del 2: Sikkerhed — Kritiske Fund

### 🔴 S1: Path Traversal i Log-API (KRITISK)

**Fil:** `app/domains/shared/handlers/log_query_handlers.py` linje 65-66

```python
logs_dir = Path(self.settings.log_directory)
file_path = logs_dir / query.filename  # INGEN SANITERING
```

API-endpoint: `GET /api/logs/{filename}/content`

**Angreb:** `GET /api/logs/..%2F..%2F..%2Fetc%2Fpasswd/content` kan læse vilkårlige filer.

**Berørte endpoints:** 3 stk (content, chunk, download)

**Fix:**
```python
file_path = (logs_dir / query.filename).resolve()
if not file_path.is_relative_to(logs_dir.resolve()):
    raise HTTPException(status_code=403, detail="Access denied")
```

### 🔴 S2: Path Traversal i Directory Browser (KRITISK)

**Fil:** `app/domains/directory_browsing/service.py` linje 76-80

```python
async def scan_custom_directory(self, directory_path: str, ...):
    return await self._scan_directory(directory_path, ...)  # INGEN VALIDERING
```

API-endpoint: `GET /api/directory/scan/custom?path=/etc`

Brugeren kan scanne vilkårlige mapper på systemet.

**Fix:**
```python
allowed = [Path(self._settings.source_directory).resolve(),
           Path(self._settings.destination_directory).resolve()]
requested = Path(directory_path).resolve()
if not any(requested == root or requested.is_relative_to(root) for root in allowed):
    raise ValueError("Path outside allowed directories")
```

### 🔴 S3: Hardcoded Credentials i Tally Light (KRITISK)

**Fil:** `app/domains/tally_light/switch_clients.py` linje 32-34

```python
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "12345678"
```

Credentials er hardcoded i source og synlige i versionskontrol.

**Fix:** Flyt til `Settings`:
```python
# config.py
tally_light_switch_username: str = "admin"
tally_light_switch_password: str = ""
```

### 🟠 S4: Ubeskyttet Restart-Endpoint

**Fil:** `app/domains/shared/api/config_api.py` linje 35

```python
@router.post("/restart-application")
async def restart_application(command_bus: ...):
```

Ingen autentificering, ingen rate limiting. Enhver med netværksadgang kan genstarte servicen.

**Fix:** Tilføj rate-limiting (max 1 restart pr. 5 minutter) eller simpel API-key:
```python
from fastapi import Header, HTTPException

async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != settings.admin_api_key:
        raise HTTPException(status_code=401)
```

### 🟠 S5: Intern Exception-info lækket til klient

**Fil:** `app/domains/directory_browsing/api.py` linje 39, 61, 88

```python
raise HTTPException(status_code=500, detail=str(e))
```

`str(e)` kan indeholde filstier, interne fejlbeskeder og stacktrace-fragmenter.

**Fix:** Log fejlen internt, returner generisk besked:
```python
logging.error(f"Directory scan error: {e}", exc_info=True)
raise HTTPException(status_code=500, detail="Internal server error")
```

### 🟠 S6: Settings-endpoint eksponerer intern konfiguration

**Fil:** `app/domains/shared/api/config_api.py` linje 18

```python
@router.get("/settings", response_model=Settings)
async def read_settings(...):
    return await query_bus.execute(GetSettingsQuery())
```

Returnerer *hele* `Settings`-objektet inkl. interne IP-adresser (`tally_light_switch_ip`, `justin_api_base_url`), filstier og thresholds.

**Fix:** Opret en `PublicSettings`-model der kun eksponerer de felter UI'et behøver.

---

## Del 3: Low-Level Kodekvalitet

### 3.1 Logging — Inkonsistent stack trace tracking

**Problem:** Kun 9 steder i hele kodebasen bruger `exc_info=True`. Alle andre `logging.error(f"...{e}")` mister stack tracen.

**Eksempler uden stack trace:**
- `app/domains/presentation/websocket_manager.py` linje 43
- `app/domains/tally_light/switch_clients.py` linje 81, 84, 87
- `app/domains/file_processing/space_retry_manager.py` linje 265
- `app/domains/network_mount/windows_mounter.py` linje 55, 99
- `app/domains/lifecycle/service.py` linje 63
- `app/domains/tally_light/monitor_service.py` linje 150, 155
- `app/domains/ingest_monitor/worker.py` linje 156, 199, 208
- `app/domains/file_discovery/file_scanner.py` linje 127, 145, 178, 209, 252, 335

**Ekstra risiko:** `logging.exception()` bruges **nul** steder. Det er den idiomatiske måde at logge exceptions med stack trace.

**Anbefaling:** Global søg-og-erstat:
```python
# Fra:
logging.error(f"Error in X: {e}")
# Til:
logging.error(f"Error in X: {e}", exc_info=True)
```

Prioriter de steder der håndterer I/O og netværk (file_scanner, worker, mounter) — det er her fejl er sværest at debugge uden stack traces.

### 3.2 WebSocket Queue er ubegrænset

**Fil:** `app/domains/presentation/websocket_manager.py` linje 15

```python
self._message_queue: Queue = Queue()  # Ingen maxsize
```

Hvis en WebSocket-klient forbinder men ikke læser (eller læser langsomt), vokser køen ubegrænset → memory exhaustion.

**Fix:**
```python
self._message_queue: Queue = Queue(maxsize=1000)
```

Og i `broadcast_message`:
```python
def broadcast_message(self, message_data: Dict[str, Any]) -> None:
    try:
        self._message_queue.put_nowait(message_data)
    except asyncio.QueueFull:
        logging.warning("WebSocket message queue full - dropping message")
```

### 3.3 HTTP-klient lukkes aldrig

**Fil:** `app/dependencies.py` → `IngestApiClient`

`IngestApiClient` opretter en `httpx.AsyncClient` men der er ingen `await client.aclose()` i shutdown-sekvensen (`app/main.py` linje 199-216).

**Fix:** Tilføj til shutdown i `main.py`:
```python
from app.dependencies import get_ingest_api_client
await get_ingest_api_client().close()
```

### 3.4 Manglende konfigurationsvalidering ved opstart

**Fil:** `app/config.py`

`source_directory` og `destination_directory` accepterer vilkårlige strenge. Hvis en bruger har en typo i settings.env, fejler systemet først ved runtime.

**Anbefaling:** Tilføj Pydantic validators:
```python
@field_validator('source_directory', 'destination_directory')
@classmethod
def validate_directory(cls, v: str) -> str:
    if not v or not v.strip():
        raise ValueError("Directory path cannot be empty")
    return v.strip()
```

*Bemærk: Tjek IKKE at mappen eksisterer i validatoren — det er StorageMonitor's opgave. Men valider at strengen ikke er tom.*

### 3.5 Pydantic V2 deprecation warning

**Fil:** `app/domains/ingest_monitor/models.py` linje 42

```python
class JustInActiveChannels(BaseModel):
    class Config:  # ← Deprecated i Pydantic V2
        ...
```

**Fix:** Erstat med `model_config = ConfigDict(...)`.

### 3.6 `_cleanup_missing_files` er en stub

**Fil:** `app/domains/file_discovery/file_scanner.py`

Metoden returnerer altid 0. Filer der forsvinder fra disk (slettet af bruger, netværk forsvinder) ryddes aldrig op fra FileRepository.

**Risiko:** Over tid vokser in-memory lageret med "spøgelses-filer" der aldrig forsvinder (indtil LifecycleService pruner efter 14 dage).

**Anbefaling:** Implementer logik der tjekker om filen stadig eksisterer og markerer den som REMOVED.

### 3.7 Exception-typer i catch-clauses

Kodebasen bruger `except Exception as e:` som primært pattern (~40+ steder). Det er generelt ok for en long-running service, men der er 2 steder med `except Exception: pass`:

- `app/domains/file_processing/consumer/job_error_classifier.py` linje 129 og 204

Begge er `Path(file_path).exists()` checks — acceptable fordi de blot falder igennem til et default-svar. Men mønsteret bør ikke spredes.

---

## Del 4: Prioriteret Handlingsplan

### Blokerende for produktion — ✅ RETTET

| # | Tiltag | Fil(er) | Status |
|---|--------|---------|--------|
| 1 | Path traversal i log-API | `shared/handlers/log_query_handlers.py` | ✅ `_safe_log_path()` med `resolve()` + `is_relative_to()` |
| 2 | Path traversal i directory browser | `directory_browsing/api.py` | ✅ Validering i API-laget med `resolve()` + `is_relative_to()` |
| 3 | Flyt credentials til config | `tally_light/switch_clients.py` + `config.py` | ✅ `tally_light_switch_username` + `tally_light_switch_password` i Settings |
| 4 | Stop-eksponering af intern exception-info | `directory_browsing/api.py` | ✅ Generisk "Internal server error" + `exc_info=True` |

### Vigtigt — ✅ RETTET

| # | Tiltag | Fil(er) | Status |
|---|--------|---------|--------|
| 5 | Rate-limit på restart-endpoint | `shared/api/config_api.py` | ✅ 5-min cooldown med HTTP 429 |
| 6 | Luk HTTP-klient ved shutdown | `main.py` | ✅ `await get_ingest_api_client().close()` |
| 7 | Shutdown timeout (30s) | `main.py` | ✅ `asyncio.wait_for(..., timeout=30.0)` |
| 8 | WebSocket queue maxsize | `presentation/websocket_manager.py` | ✅ `Queue(maxsize=5000)` + drop-oldest overflow |
| 9 | Settings-endpoint: filtrer sensitive felter | `shared/api/config_api.py` | ✅ Ny `PublicSettings` model |
| 10 | Tilføj `exc_info=True` til error-logs | 29 filer | ✅ 83 logging.error() calls rettet |

### Nice-to-have — ✅ RETTET

| # | Tiltag | Fil(er) | Status |
|---|--------|---------|--------|
| 11 | Fire-and-forget task references | `file_state_machine.py`, `copy_io_loop.py`, `network_error_detector.py`, `growing_copy.py` | ✅ `_pending_tasks` set + `add_done_callback` |
| 12 | Fix Pydantic V2 deprecation + refaktor `_singletons` | `ingest_monitor/models.py`, `main.py`, `dependencies.py` | ✅ `model_config = {}` + `register_network_coordinator()` |

### Resterende anbefalinger (ikke-blokerende)

| # | Tiltag | Indsats | Effekt |
|---|--------|---------|--------|
| 13 | SQLite persistence for FileRepository | 4-8 timer | Data overlever genstart |
| 14 | Implementer `_cleanup_missing_files` | 2 timer | Oprydning af spøgelses-filer |
| 15 | Tom-streng validering i config | 15 min | Hurtigere fejl ved mis-config |

---

## Del 5: Hvad der IKKE behøver at blive ændret

Disse ting er *allerede* velbyggede og produktionsklare:

- **FileStateMachine:** Lock-baseret atomicitet med veldefinerede transitions. Udsteder events udenfor lock.
- **EventBus:** Fejl-isolation pr. subscriber. Ét domæne kan fejle uden at påvirke andre.
- **Copy IO Loop:** Chunk retry med exponential backoff, 2-sekunders timeout pr. I/O, korrekt progress-reporting.
- **Growing File Copy:** Safety margin, pause-mekanisme, min-size gate, vækst-detektion.
- **Network Error Detector:** 22 string-patterns + errno-koder + Windows-specifikke koder. Meget grundig.
- **Dependency pinning:** Alle versioner pinned eksakt. Ingen floating dependencies.
- **Background task tracking i main.py:** Alle 7 tasks gemt i `_background_tasks`, proper cancel + gather ved shutdown.
- **StorageMonitor SRP:** God nedbrydning i 4 sub-klasser. Parallel mount-guard forhindrer race conditions.
- **CQRS registrering per domæne:** Klart overblik over hvad hvert domæne eksponerer.
