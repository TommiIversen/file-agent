# Roadmap: File Transfer Agent

Dette dokument beskriver udviklingsplanen for `File Transfer Agent`. Projektet bygges i logiske, testbare faser for at sikre robusthed og en klar udviklingsproces. Hver fase afsluttes med specifikke testkrav.

**Grundlæggende Principper:**
* **Sprog:** Python 3.11+
* **Framework:** FastAPI
* **Asynkron I/O:** `asyncio`, `aiofiles`
* **Principper:** Clean Code, SOLID (løs kobling, single responsibility). Formelle interfaces (`abc`) benyttes ikke.
* **Dependency Management:** Alle services og afhængigheder registreres i `app/dependencies.py`.
* **Test:** `pytest` benyttes til at validere funktionalitet efter hver fase.
* **Logging:** Struktureret logging med både konsol og rullende log-filer (development vs. production).
* **Konfiguration:** Pydantic Settings for type-safe konfiguration med `.env` fil support.
* **Forudsætning:** Et testværktøj ("File Growth Simulator") eksisterer allerede og kan bruges til at generere testfiler.

---

## Fase 0: Projektopsætning og Fundament

### Mål
At etablere en grundlæggende projektstruktur med FastAPI, dependency injection, logging, konfiguration og de nødvendige biblioteker, så vi har et robust skelet.

### Moduler/Filer
* `pyproject.toml`: Definerer projektets afhængigheder (`fastapi`, `uvicorn`, `aiofiles`, `pytest`, `pydantic-settings`, `structlog`).
* `app/main.py`: Indeholder den primære FastAPI-app-instans og et "hello world"-endpoint.
* `app/dependencies.py`: Tom fil, klargjort til at håndtere dependency injection (DI).
* `app/config.py`: Type-safe konfigurationssystem med Pydantic Settings.
* `app/logging_config.py`: Centraliseret logging setup.
* `.env`: Miljøvariable konfigurationsfil.

### Konfigurationsvariabler (inspireret af C# appsettings.json)
```python
class Settings(BaseSettings):
    # Filstier
    source_path: str = "/tmp/source"
    destination_path: str = "/tmp/destination"
    
    # Timing konfiguration
    file_stable_time_seconds: int = 120
    polling_interval_seconds: int = 10
    
    # Filkopiering
    use_temporary_file: bool = True
    max_retry_attempts: int = 3
    retry_delay_seconds: int = 10
    global_retry_delay_seconds: int = 60
    
    # Logging
    log_level: str = "INFO"
    log_file_path: str = "logs/file_agent.log"
    
    class Config:
        env_file = ".env"
```

### Logging System
* **Konsol logging:** Under udvikling med farvet output
* **Fil logging:** Rullende log-filer i production
* **Log niveauer:**
  - `INFO`: Almindelige hændelser ("Applikation startet", "Fil opdaget")
  - `WARNING`: Problematiske hændelser ("Navnekonflikt", "Retry forsøg")
  - `ERROR`: Reelle fejl ("Netværksfejl", "Fil kan ikke læses")

### Implementerings-steps
1.  Opret projektmappen og et virtuelt miljø.
2.  Definer afhængigheder i `pyproject.toml` og installer dem.
3.  Implementer `app/config.py` med Pydantic Settings.
4.  Implementer `app/logging_config.py` med struktureret logging.
5.  Opret `app/main.py` med FastAPI-app og `GET /` endpoint der returnerer `{"status": "ok"}`.
6.  Opret tom `app/dependencies.py`.
7.  Opret `.env` fil med standard konfiguration.

### Testkrav (pytest)
* **Test 1:** Verificer at `GET /` endpointet svarer med HTTP-status 200 og `{"status": "ok"}`.
* **Test 2:** Verificer at konfigurationssystemet korrekt læser fra `.env` fil.
* **Test 3:** Verificer at logging fungerer både til konsol og fil.

---

## Fase 1: Central State Management (Hjernen 🧠)

### Mål
At bygge den centrale "single source of truth" for hele applikationen. Denne service skal kunne holde styr på alle filer og deres status på en trådsikker måde.

### Moduler/Filer
* `app/models.py`:
    * `FileStatus` (Enum): `Discovered`, `Ready`, `InQueue`, `Copying`, `Completed`, `Failed`.
    * `TrackedFile` (Pydantic Model): Indeholder `file_path: str`, `status: FileStatus`, `file_size: int`, `last_write_time: datetime`, `copy_progress: float`, `error_message: Optional[str]`, `retry_count: int`.
* `app/services/state_manager.py`:
    * `StateManager` (Klasse): Holder en `dict[str, TrackedFile]` (key = file_path). Implementerer metoder til at tilføje, opdatere og fjerne filer. Implementerer pub/sub-system (`subscribe`, `_notify`). Alle metoder skal være trådsikre med `asyncio.Lock`.
* `app/dependencies.py`:
    * Registrer `StateManager` som en **singleton** service.

### StateManager Metoder
```python
class StateManager:
    async def add_file(self, file_path: str, file_size: int) -> TrackedFile
    async def update_file_status(self, file_path: str, status: FileStatus, **kwargs)
    async def remove_file(self, file_path: str)
    async def get_file(self, file_path: str) -> Optional[TrackedFile]
    async def get_all_files(self) -> List[TrackedFile]
    async def get_files_by_status(self, status: FileStatus) -> List[TrackedFile]
    def subscribe(self, callback: Callable[[TrackedFile], None])
    async def cleanup_missing_files(self, existing_paths: Set[str])
```

### Implementerings-steps
1.  Implementer `FileStatus` enum og `TrackedFile` Pydantic model i `app/models.py`.
2.  Implementer `StateManager`-klassen med `asyncio.Lock` omkring alle modificerende operationer.
3.  Implementer pub/sub system: `subscribe(callback)` og `_notify(tracked_file)`.
4.  Implementer `cleanup_missing_files()` metode til at fjerne filer der ikke længere eksisterer.
5.  Registrer `StateManager` som singleton i `app/dependencies.py`.

### Testkrav (pytest)
* **Test 1:** Verificer at `StateManager.add_file()` korrekt tilføjer et `TrackedFile` med status `Discovered`.
* **Test 2:** Verificer at `StateManager.update_file_status()` ændrer status og kalder subscribers.
* **Test 3:** Verificer at `cleanup_missing_files()` fjerner filer der ikke er i `existing_paths`.
* **Test 4:** Verificer thread-safety ved at køre parallelle operationer.

---

## Fase 2: File Scanner (Øjnene 👀)

### Mål
At implementere en baggrunds-worker, der overvåger filsystemet, synkroniserer med `StateManager`, og identificerer "stabile" filer der er klar til kopiering.

### Moduler/Filer
* `app/services/file_scanner.py`:
    * `FileScannerService` (Klasse): Indeholder scanning logik og fil-stabilitet vurdering.
    * `scan_folder_loop()` (async-funktion): Hovedloop der kører kontinuerligt.
* `app/main.py`:
    * Tilføj startup event til at starte `scan_folder_loop` som baggrundsopgave.

### File Scanner Logik (Inspireret af C# FileScannerService)
```python
class FileScannerService:
    async def scan_folder_loop(self):
        while True:
            # 1. Cleanup: Fjern filer fra StateManager der ikke eksisterer på disk
            # 2. Discovery: Find nye filer og tilføj med status Discovered  
            # 3. Stability Check: Vurder om Discovered filer er "stabile"
            # 4. Ready Promotion: Opdater stabile filer til Ready status
            await asyncio.sleep(config.polling_interval_seconds)
    
    async def is_file_stable(self, file_path: str) -> bool:
        # Fil er stabil hvis LastWriteTime er uændret i FILE_STABLE_TIME_SECONDS
        # Bonus: Forsøg eksklusiv fil-lås for ekstra verifikation
```

### Fil-stabilitet Identifikation (Fra C# spec)
En fil anses for "færdig" når:
1. **LastWriteTime** har været uændret i `config.file_stable_time_seconds`
2. **Optional:** Kortvarig eksklusiv lås kan opnås på filen
3. **Fil-størrelse > 0** (ikke tom fil)

### Implementerings-steps
1.  Implementer `FileScannerService` klasse med alle scanning metoder.
2.  Implementer `is_file_stable()` med LastWriteTime tracking.
3.  Implementer cleanup logik der bruger `StateManager.cleanup_missing_files()`.
4.  Implementer discovery logik der scanner `config.source_path` rekursivt.
5.  Integrer med logging system (INFO: fil fundet, WARNING: ustabil fil).
6.  Start `scan_folder_loop` som background task i `app/main.py`.

### Recovery og Genstart (Fra C# spec)
* **Princip:** Ved opstart skal systemet kunne genopbygge tilstand fra filsystemet
* **Implementering:** Første scanning bygger fresh tilstand baseret på fysiske filer
* **Cleanup:** Fjern TrackedFile objekter for filer der er blevet flyttet/slettet

### Testkrav (pytest)
* **Test 1:** Verificer at scanner opdager ny fil og tilføjer til `StateManager` med `Discovered`.
* **Test 2:** Brug "File Growth Simulator" - verificer at fil først er `Discovered`, senere `Ready`.
* **Test 3:** Verificer at slettede filer fjernes fra `StateManager`.
* **Test 4:** Test recovery - restart scanner og verificer korrekt genopbygning af tilstand.

---

## Fase 3: Job-Køen (Postkassen 📥)

### Mål
At afkoble `FileScanner` fra `FileCopyer` ved at introducere en asynkron job-kø.

### Moduler/Filer
* `app/dependencies.py`:
    * Registrer en `asyncio.Queue` som en **singleton**.
* `app/services/file_scanner.py`:
    * Opdater `scan_folder_loop` til også at tage `asyncio.Queue` som afhængighed.

### Implementerings-steps
1.  Implementer `asyncio.Queue` singleton i `app/dependencies.py`.
2.  Opdater `FileScannerService`: Når fil bliver `Ready`, tilføj `file_path` til queue og opdater status til `InQueue`.
3.  Implementer queue producer logik i file scanner.
4.  Sørg for korrekt separation af concerns mellem queue (midlertidig indbakke) og StateManager (permanent opslagstavle).

### Producer/Consumer Pattern (Fra C# Channels koncept)
* **Queue som singleton:** Én delt `asyncio.Queue` instans på tværs af hele applikationen
* **Producer:** `FileScannerService` tilføjer file paths når filer er Ready
* **Consumer:** `FileCopyService` (næste fase) henter file paths fra queue
* **Separation:** Queue er midlertidig arbejdsliste, StateManager er permanent tilstandslagring

### Testkrav (pytest)
* **Test 1:** Verificer, at når en fil bliver `Ready`, bliver dens sti tilføjet til `asyncio.Queue`.
* **Test 2:** Verificer, at filens status i `StateManager` samtidig opdateres til `InQueue`.

---

## Fase 4: File Copier (Arbejdshesten 👷)

### Mål
At implementere en robust baggrunds-worker der tager jobs fra køen og udfører pålidelig filkopiering med avanceret fejlhåndtering og verifikation.

### Moduler/Filer
* `app/services/file_copier.py`:
    * `FileCopyService` (Klasse): Håndterer al kopieringslogik og fejlhåndtering.
    * `copy_file_loop()` (async-funktion): Hovedloop der lytter på job queue.
* `app/main.py`:
    * Start `copy_file_loop` som baggrundsopgave.

### Robust Filkopiering (Fra C# spec)
```python
class FileCopyService:
    async def copy_file_with_verification(self, file_path: str):
        # 1. Opdater status til Copying i StateManager
        # 2. Genskap relative mappestruktur på destination  
        # 3. Håndter navnekonflikter (_1, _2, etc.)
        # 4. Kopier til .tmp fil (hvis use_temporary_file=True)
        # 5. Rapporter copy_progress løbende til StateManager
        # 6. Verificer filstørrelse (source == destination)
        # 7. Omdøb .tmp til final navn
        # 8. Slet original kildefil
        # 9. Opdater status til Completed
```

### Fejlhåndtering System (Fra C# spec)
**Global Fejl (Destination utilgængelig):**
- NAS offline, netværksdrev afmonteret, generelle netværksproblemer
- **Håndtering:** Pause hele køen, uendelig retry med `config.global_retry_delay_seconds`
- **Logging:** WARNING niveau, vent indtil destination kommer online

**Lokal Fejl (Specifik fil):**
- Fil låst, forkerte rettigheder, korrupt fil
- **Håndtering:** Max `config.max_retry_attempts` med `config.retry_delay_seconds` pause
- **Permanent fejl:** Status → `Failed`, log ERROR, fortsæt til næste job

### Verifikation og Oprydning (Fra C# spec)
* **Integritetscheck:** Verificer filstørrelse i bytes (source == destination)
* **Midlertidig fil:** Kopier til `.tmp`, omdøb først efter verifikation
* **Oprydning:** Slet kun original efter fuldt verificeret kopi
* **Progress tracking:** Opdater `copy_progress` i StateManager løbende

### Navnekonflikt Håndtering
```python
async def resolve_name_conflict(self, destination_path: str) -> str:
    # video.mxf → video_1.mxf → video_2.mxf etc.
    if not path.exists(destination_path):
        return destination_path
    
    base, ext = path.splitext(destination_path)
    counter = 1
    while path.exists(f"{base}_{counter}{ext}"):
        counter += 1
    return f"{base}_{counter}{ext}"
```

### Implementerings-steps
1.  Implementer `FileCopyService` klasse med al kopieringslogik.
2.  Implementer differentieret fejlhåndtering (global vs. lokal).
3.  Implementer navnekonflikt resolution.
4.  Implementer filstørrelses-verifikation.
5.  Implementer progress tracking med StateManager opdateringer.
6.  Implementer .tmp fil strategi (hvis konfigureret).
7.  Integrer med logging system (INFO: succes, WARNING: retry, ERROR: permanent fejl).
8.  Start `copy_file_loop` som background task.

### Testkrav (pytest)
* **End-to-end test:** Brug "File Growth Simulator" → fil kopieret → slettet fra source → status `Completed`.
* **Navnekonflikt test:** Kopier fil med samme navn → verificer `_1` suffix.
* **Fejlhåndtering test:** Simuler destination utilgængelig → verificer uendelig retry.
* **Recovery test:** Simuler fil låst → verificer max retry attempts → status `Failed`.
* **Verifikation test:** Simuler korrupt kopi → verificer fejl detection.

---

## Fase 5: API Endpoints (Kontroltårnet 🗼)

### Mål
At eksponere applikationens tilstand via et detaljeret REST API til ekstern overvågning og integration.

### Moduler/Filer
* `app/api/status.py`:
    * FastAPI `APIRouter` med alle monitoring endpoints.
* `app/services/storage_monitor.py`:
    * Background service til diskplads overvågning.

### API Endpoints (Fra C# spec)

#### 1. GET /api/status - Fil Status Overview
**Output format:**
```json
{
  "pendingFilesCount": 2,
  "pendingFiles": ["clip1.mxf", "clip2.mxf"],
  "inProgress": {
    "file": "active_clip.mxf", 
    "progressPercentage": 67,
    "status": "Copying",
    "startTime": "2025-10-08T10:30:00Z"
  },
  "recentlyCompleted": [
    {"file": "completed1.mxf", "completedAt": "2025-10-08T10:25:00Z"},
    {"file": "completed2.mxf", "completedAt": "2025-10-08T10:20:00Z"}
  ],
  "failedFiles": [
    {"file": "failed.mxf", "error": "File locked", "failedAt": "2025-10-08T10:15:00Z"}
  ]
}
```

#### 2. GET /api/storage - Diskplads Overvågning
**HTTP 200 OK (Alt i orden):**
```json
{
  "sourceFreeGB": 512,
  "destinationFreeGB": 2048, 
  "status": "OK"
}
```

**HTTP 507 Insufficient Storage (Lav plads):**
```json
{
  "sourceFreeGB": 512,
  "destinationFreeGB": 80,
  "status": "WARNING",
  "message": "Destination storage is running low."
}
```

**HTTP 503 Service Unavailable (Destination utilgængelig):**
```json
{
  "sourceFreeGB": 512,
  "destinationFreeGB": -1,
  "status": "ERROR", 
  "message": "Destination path is not accessible."
}
```

#### 3. GET /api/health - Nagios Health Check
**Output:** text/plain
- HTTP 200: `"OK"`
- HTTP 503: `"ERROR"`

#### 4. GET /api/files - Detaljeret Fil Liste
**Output:** Liste af alle tracked filer med komplet metadata
```json
{
  "files": [
    {
      "file_path": "/source/video1.mxf",
      "status": "Copying", 
      "file_size": 1073741824,
      "last_write_time": "2025-10-08T10:30:00Z",
      "copy_progress": 67.5,
      "retry_count": 0,
      "error_message": null
    }
  ]
}
```

### Storage Monitor Service
```python
class StorageMonitorService:
    async def monitor_storage_loop(self):
        # Tjek hver minut med asyncio.sleep(60)
        # Beregn free space på source og destination
        # Detekter hvis destination er utilgængelig
        # Log WARNING/ERROR ved problemer
```

### Implementerings-steps
1.  Implementer alle API endpoints i `app/api/status.py`.
2.  Implementer `StorageMonitorService` med periodisk diskplads tjek.
3.  Integrer storage monitor som background task.
4.  Implementer detaljerede response modeller med Pydantic.
5.  Tilføj error handling og logging til alle endpoints.
6.  Registrer API router i `app/main.py`.

### Testkrav (pytest)
* **Test 1:** Under filkopiering, kald `GET /api/status` → verificer fil med status `Copying`.
* **Test 2:** Verificer `GET /api/health` returnerer HTTP 200 `"OK"`.
* **Test 3:** Test storage endpoint med utilgængelig destination → HTTP 503.
* **Test 4:** Verificer alle response formater matcher specifikationen.

---

## Fase 5.5: Test Framework og Unit Tests (Kvalitetssikring 🧪)

### Mål
At implementere omfattende unit tests for kritisk forretningslogik, inspireret af C# specifikationens testkrav.

### Test Kategorier (Fra C# spec)

#### 1. Navnekonflikt Logik Tests
```python
def test_name_conflict_resolution():
    # Test at video.mxf korrekt bliver til video_1.mxf
    # Test multiple konflikter: video_1.mxf → video_2.mxf
    # Test edge cases: lange filnavne, specielle tegn
```

#### 2. Fil-stabilitet Logik Tests  
```python
def test_file_stability_detection():
    # Test at fil med uændret LastWriteTime bliver "stabil"
    # Test at fil der stadig skrives til forbliver "ustabil"
    # Test edge cases: fil låst, fil slettet under check
```

#### 3. Fejlhåndtering Tests
```python
def test_global_vs_local_error_handling():
    # Mock destination utilgængelig → verificer uendelig retry
    # Mock fil låst → verificer max retry attempts
    # Test error recovery scenarios
```

#### 4. StateManager Thread-Safety Tests
```python
async def test_concurrent_state_operations():
    # Parallel add/update/remove operationer
    # Race condition detection
    # Pub/sub system under load
```

#### 5. Integration Tests med File Growth Simulator
```python
async def test_end_to_end_workflow():
    # Start simulator → stop simulator → verificer complete workflow
    # Test med multiple filer samtidigt
    # Test system recovery efter crash
```

### Test Utilities
* Mock fil system operations
* Temporary directories for test isolation  
* Async test fixtures
* File simulator integration helpers

### Implementerings-steps
1.  Opret `tests/` directory struktur.
2.  Implementer test utilities og fixtures.
3.  Skriv unit tests for hver kritisk komponent.
4.  Implementer integration tests med File Growth Simulator.
5.  Setup CI/CD pipeline til at køre tests automatisk.

### Testkrav
* **90%+ code coverage** på kritisk forretningslogik
* **All edge cases** dækket af tests
* **Performance tests** for high-load scenarios
* **Integration tests** med realistiske data

---

## Fase 6: Real-tids UI (Live-skærmen 📺)

### Mål
At skabe en simpel web-grænseflade, der viser systemets tilstand i realtid via WebSockets.

### Moduler/Filer
* `app/services/websocket_manager.py`:
    * `WebSocketManager` (Klasse): Håndterer aktive forbindelser og broadcaster beskeder.
* `app/api/websockets.py`:
    * Definerer `GET /ws` WebSocket endpointet.
* `static/index.html` & `static/app.js`:
    * Simpel HTML-side og JavaScript til at håndtere WebSocket-forbindelsen og opdatere DOM.

### Implementerings-steps
1.  Implementer `WebSocketManager`. Den skal abonnere på `StateManager`'s `StateChanged`-event.
2.  Implementer `GET /ws` endpointet. Ved ny forbindelse skal den sende et komplet "dump" af den nuværende tilstand og derefter lytte.
3.  `WebSocketManager`'s event-handler skal broadcaste små, specifikke opdateringer til alle klienter.
4.  Lav en simpel `index.html` og den nødvendige JavaScript til at vise dataen.
5.  Registrer `WebSocketManager` som en singleton i `dependencies.py`.

### Testkrav (pytest)
* **Manuel Test:**
    * **Test 1:** Åbn `index.html` i en browser.
    * **Test 2:** Kør "File Growth Simulator".
    * **Verificer:** At websiden opdaterer sig selv i realtid, og viser filen gå gennem statusserne `Discovered` -> `InQueue` -> `Copying` -> `Completed` (hvor den forsvinder fra den aktive liste).

---

## Fase 7: Produktions-klar Deployment (🚀)

### Mål
At gøre systemet klar til produktionsbrug med robust logging, monitoring, og deployment features.

### Features for Produktion

#### 1. Avanceret Logging System
* **Structured logging** med JSON format for log aggregation
* **Rullende log-filer** med automatisk oprydning
* **Different log levels** for development vs. production
* **Remote logging** integration (syslog, centralized logging)

#### 2. Health Monitoring og Metrics
* **System metrics:** CPU, memory, disk usage
* **Application metrics:** Files processed, error rates, queue lengths
* **Alerting system:** Email/webhook notifications ved kritiske fejl
* **Prometheus metrics** export for monitoring integration

#### 3. Configuration Management
* **Environment-specific** konfiguration (dev/staging/prod)
* **Secret management** for credentials og sensitive paths
* **Runtime konfiguration** reload uden genstart
* **Validation** af konfiguration ved opstart

#### 4. Background Service Management
* **Graceful shutdown** handling
* **Service restart** robusthed
* **Systemd integration** på Linux
* **Windows Service** support på Windows

#### 5. Database Integration (Optional)
* **Persistent state** storage for større systemer
* **File operation audit log** for compliance
* **Historical data** og reporting capabilities

### Implementerings-steps
1.  Implementer produktions-logging konfiguration.
2.  Tilføj system metrics og health monitoring.
3.  Implementer graceful shutdown handlers.
4.  Opret deployment scripts og documentation.
5.  Setup monitoring dashboards.
6.  Implementer backup og disaster recovery procedures.

### Deployment Targets
* **Docker containerization** med multi-stage builds
* **Kubernetes deployment** manifests
* **Traditional server** deployment guides
* **Cloud deployment** (AWS/Azure/GCP) templates

---

## Tidsestimering (Fra C# spec)

### Fase-by-fase estimat:
* **Fase 0:** Projektopsætning og fundament: **8-12 timer**
* **Fase 1:** Central State Management: **12-16 timer** 
* **Fase 2:** File Scanner Service: **15-20 timer**
* **Fase 3:** Job Queue system: **5-8 timer**
* **Fase 4:** File Copier Service: **20-30 timer**
* **Fase 5:** API Endpoints: **8-12 timer**
* **Fase 5.5:** Test Framework: **10-15 timer**
* **Fase 6:** Real-tids UI: **15-20 timer**
* **Fase 7:** Produktions-deployment: **8-12 timer**

### Samlet estimat:
* **Minimum:** 101 timer (≈ 2.5 fulde arbejdsuger)
* **Realistisk:** 145 timer (≈ 3.5 fulde arbejdsuger)  
* **Med buffer:** 170 timer (≈ 4 fulde arbejdsuger)

*Note: Dette estimat antager erfaren Python/FastAPI udvikler. Læringskurve kan tilføje 25-50% ekstra tid.*