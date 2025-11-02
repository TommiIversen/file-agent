Fremtidig Refaktoriseringsplan (Version 2.0)
Status: 2. november 2025. StateManager er elimineret. Denne plan dækker de sidste 10% af arkitektonisk oprydning.

🎯 Resterende Hovedopgaver
Implementer Netværkskoordinator: Løs problemet med "Cross-Cutting Concerns" ved at centralisere al netværkstilstands-logik, så FileScanner og JobQueue ikke længere er afhængige af StorageMonitor.

"Slice" Kopi-processen (Consumer): Opløs den nye "God Handler" (command_handlers.py på 657 linjer) og den store growing_copy.py (419 linjer) til en ren, orkestreret proces.

Fuldfør CQRS-migrering: Omdan de sidste "gamle" services (directory_browsing/service.py og storage_monitor/storage_monitor.py) til CQRS-handlers for at opnå en 100% konsistent arkitektur.

Opgave 1: Implementer Netværkskoordinator
## Problem: Kompleks netværksstatus-arkitektur (IKKE kun 2 kilder!)

**Faktisk analyse afslører 7+ kilder til netværksstatus:**

1. **StorageMonitor** (Officiel kilde): Periodisk tjek hver 30s via `get_destination_info()`
2. **NetworkErrorDetector** (Reaktiv): Fejldetektion under kopieringsoperationer (rejser exceptions, INGEN events)
3. **CommandHandler._is_network_available()** (Duplikeret logik): Direkte state access til StorageMonitor
4. **JobErrorClassifier** (Indirekte): Checker `storage_monitor.get_destination_info()` for fejlklassificering
5. **SpaceChecker** (Indirekte): Checker `storage_monitor.get_destination_info()` for pladskonkrol
6. **PresentationHandlers** (UI): Direkte adgang til StorageMonitor for UI-status
7. **SharedStorageHandlers** (API): API endpoints der eksponerer storage status

**Nuværende Arkitektur (Faktisk tilstand):**
```mermaid
graph TD
    A[StorageMonitor] -- "Periodisk tjek (30s)" --> B[Internal State]
    
    C[NetworkErrorDetector] -- "Rejser NetworkError" --> D[Copy Error Handling]
    
    B --> E[CommandHandler._is_network_available - DUPLIKERET LOGIK!]
    B --> F[JobErrorClassifier.storage_monitor.get_destination_info]
    B --> G[SpaceChecker.storage_monitor.get_destination_info] 
    B --> H[PresentationHandlers.storage_monitor.get_*]
    B --> I[SharedStorageHandlers.storage_monitor.get_*]
    
    E -- "Direkte kobling" --> J[File Processing Logic]
    F -- "Direkte kobling" --> K[Job Error Handling]
    G -- "Direkte kobling" --> L[Copy Operations]
    H -- "Direkte kobling" --> M[Frontend]
    I -- "Direkte kobling" --> N[API Clients]
    
    A -- "Direkte kalder JobQueue!" --> O[JobQueueService]
```

**Målet - NetworkCoordinator Arkitektur:**
```mermaid
graph TD
    A[NetworkErrorDetector] -- "NetworkFailureDetectedEvent" --> C[NetworkCoordinator]
    B[StorageMonitor] -- "DestinationUnavailableEvent/RecoveredEvent" --> C
    C -- "NetworkStatusChanged(available=bool)" --> D[EventBus]
    D --> E[FileScannerService - Event Handler]
    D --> F[JobQueueService - Event Handler]
    D --> G[PresentationEventHandlers - Event Handler]
    D --> H[SpaceChecker - Event Handler]
    D --> I[JobErrorClassifier - Event Handler]
```
## Handlingsplan - FASE-OPDELT TILGANG

### FASE 1: Grundlæggende Event Infrastructure
**Mål:** Etabler event-baseret kommunikation mellem StorageMonitor og NetworkErrorDetector

**1.1 Definer Nye Events**
Fil: `app/core/events/storage_events.py` (tilføj til eksisterende fil)

```python
@dataclass(frozen=True)
class DestinationUnavailableEvent(DomainEvent):
    """Publiceres NÅR destinationen går fra OK -> ERROR/CRITICAL."""
    reason: str
    storage_info: StorageInfo

@dataclass(frozen=True) 
class DestinationRecoveredEvent(DomainEvent):
    """Publiceres NÅR destinationen går fra ERROR/CRITICAL -> OK."""
    reason: str
    storage_info: StorageInfo

@dataclass(frozen=True)
class NetworkFailureDetectedEvent(DomainEvent):
    """Publiceres når NetworkErrorDetector finder en netværksfejl under kopiering."""
    error_message: str
    file_id: str
    operation: str
```

**1.2 Refaktorér NetworkErrorDetector til at publicere events**
Fil: `app/domains/file_processing/copy/network_error_detector.py`
- Tilføj `event_bus: DomainEventBus` til `__init__`
- Modificer `check_write_error()` til at publicere `NetworkFailureDetectedEvent` før den rejser `NetworkError`

### FASE 2: Opret NetworkCoordinator
**Mål:** Central koordinator for alle netværksstatus-beslutninger

**2.1 Opret NetworkCoordinator**
Fil: `app/domains/network_mount/network_coordinator.py`

```python
class NetworkCoordinator:
    """
    Central koordinator for netværksstatus. 
    Lytter efter NetworkFailureDetectedEvent og Storage events.
    Publicerer autoritativ NetworkStatusChanged event.
    """
    def __init__(self, event_bus: DomainEventBus):
        self._event_bus = event_bus
        self._network_available: bool = True
        
    async def handle_network_failure_detected(self, event: NetworkFailureDetectedEvent):
        """Håndter øjeblikkelig netværksfejl fra copy operationer."""
        
    async def handle_destination_unavailable(self, event: DestinationUnavailableEvent):
        """Håndter periodisk fejl fra StorageMonitor."""
        
    async def handle_destination_recovered(self, event: DestinationRecoveredEvent):
        """Håndter recovery fra StorageMonitor."""
        
    async def _update_network_status(self, available: bool, reason: str):
        """Opdater status og publicer NetworkStatusChanged event."""
```

**2.2 Registrer NetworkCoordinator**
- Tilføj til `app/domains/network_mount/registration.py`
- Abonner på alle 3 event typer

### FASE 3: Refaktorér StorageMonitor 
**Mål:** Fjern direkte kobling til JobQueue, publicer events i stedet

**3.1 Fjern JobQueue dependency**
Fil: `app/domains/storage_monitor/storage_monitor.py`
- Fjern `job_queue: JobQueueService` fra `__init__`

**3.2 Erstat direkte kald med events**
- `_handle_destination_unavailable`: Fjern `self._job_queue.handle_destination_unavailable()`, tilføj `await self._event_bus.publish(DestinationUnavailableEvent(...))`
- `_handle_destination_recovery`: Fjern `self._job_queue.process_waiting_network_files()`, tilføj `await self._event_bus.publish(DestinationRecoveredEvent(...))`

### FASE 4: Refaktorér JobQueueService
**Mål:** Gør JobQueue til event subscriber i stedet for at have direkte storage dependency

**4.1 Fjern storage_monitor dependency**
Fil: `app/domains/file_processing/job_queue.py`
- Fjern `storage_monitor` fra `__init__` 
- Slet `_is_network_available()` metoden

**4.2 Simplificer handle_file_ready**
- Fjern `if await self._is_network_available():` tjek
- Logik: "Hvis FileReadyEvent modtages, tilføj ALTID til kø"

**4.3 Flyt network event handling**
- Flyt `handle_destination_unavailable` og `process_waiting_network_files` til nye event handlers
- Opret `app/domains/file_processing/network_event_handlers.py`

**4.4 Opdater registration**
Fil: `app/domains/file_processing/registration.py`
- Abonner på `NetworkStatusChanged` events

### FASE 5: Refaktorér CommandHandler
**Mål:** Fjern duplikeret `_is_network_available` logik

**5.1 Slet duplikeret network checking**
Fil: `app/domains/file_processing/command_handlers.py`
- Slet `_is_network_available()` metoden
- Fjern network checking fra `handle_file_ready`

**5.2 Tilføj network event handling**  
- Lyt efter `NetworkStatusChanged` events
- Sæt filer til `WAITING_FOR_NETWORK` når netværk bliver utilgængeligt

### FASE 6: Refaktorér Resterende Dependencies
**Mål:** Fjern direkte storage_monitor access fra alle andre steder

**6.1 SpaceChecker**
- Lyt efter `NetworkStatusChanged` i stedet for direkte `storage_monitor.get_destination_info()`

**6.2 JobErrorClassifier** 
- Lyt efter network events i stedet for direkte storage access

**6.3 PresentationHandlers**
- Behold direkte access til storage_monitor for UI (eller overvej caching via NetworkCoordinator)

**6.4 SharedStorageHandlers**
- Behold direkte access til storage_monitor for API responses

### FASE 7: Validering og Test
**Mål:** Sikr at ny arkitektur virker korrekt

**7.1 Integration test**
- Test at NetworkCoordinator reagerer på både øjeblikkelige og periodiske fejl
- Test at alle subscribers reagerer korrekt på NetworkStatusChanged

**7.2 Performance test**
- Verificer at event-baseret tilgang ikke introducerer latency
- Test failover og recovery scenarier

Opgave 2: "Slice" Kopi-processen (Consumer)
Problem: Du har rullet ændringer til growing_copy.py tilbage. Din file_processing/command_handlers.py er nu 657 linjer, hvilket indikerer, at du har skabt en ny "God Handler", sandsynligvis en ProcessJobCommandHandler, der gør alt det arbejde, som de små consumer-services burde gøre.

Løsning: Gå tilbage til "Composition"-modellen, som JobProcessor oprindeligt brugte. En "slice" er en proces, ikke én fil.

Handlingsplan (for AI-agent)
Slet "God Handleren":

Fil: app/domains/file_processing/command_handlers.py

Handling: Slet den store ProcessJobCommandHandler (som sandsynligvis indeholder logikken fra JobProcessor.process_job).

Fil: app/domains/file_processing/commands.py

Handling: Slet ProcessJobCommand.

Gendan JobProcessor som Orkestrator:

Fil: app/domains/file_processing/consumer/job_processor.py

Verificer: Sikr dig, at denne klasse er en "tynd orkestrator" som i hovedmoduler_analyse.md. Den skal ikke have nogen CQRS-roller. Dens process_job-metode er den "use case slice".

Verificer: Sikr dig, at JobProcessor's __init__ modtager alle sine hjælpere via DI (JobSpaceManager, JobFinalizationService, JobFilePreparationService, JobCopyExecutor).

Refaktorér FileCopierService (Worker):

Fil: app/domains/file_processing/copy/file_copier_service.py

Handling: Denne klasse er din worker. Den skal ikke kalde CommandBus.

Opdater __init__: Fjern CommandBus-afhængigheden. Tilføj job_processor: JobProcessor og job_queue: JobQueueService.

Opdater worker-loop (_run_worker):

Fjern: await self.command_bus.execute(ProcessJobCommand(job=job))

Tilføj: Den klassiske worker-loop:

Python

job = await self.job_queue.get_next_job()
if job:
    process_result = await self.job_processor.process_job(job)
    if process_result.success:
        await self.job_queue.mark_job_completed(job, process_result.processing_time)
    else:
        await self.job_queue.mark_job_failed(job, process_result.error_message, process_result.processing_time)
Refaktorér growing_copy.py (Den Tilbage-rullede Opgave):

Fil: app/domains/file_processing/copy/growing_copy.py (419 linjer).

Mål: Denne fil skal kun indeholde orkestreringslogikken. Den har allerede (korrekt) uddelegeret I/O til CopyIoLoop og verificering til FileVerificationService.

Problem: Den har stadig _is_file_currently_growing og _growing_copy_loop (den store orkestrerings-loop).

Handling: Opret en ny, "tyndere" orkestreringsklasse (f.eks. CopyOrchestrator) og flyt den komplekse _growing_copy_loop og copy_file logik dertil. Lad GrowingFileCopyStrategy blive en "dum" dataklasse eller en meget tynd facade.

Handling: Flyt _is_file_currently_growing til JobFilePreparationService, da det er dér, beslutningen om GROWING_COPY vs. COPYING tages.

Opgave 3: Fuldfør CQRS-migrering (Resterende Domæner)
Refaktorér directory_browsing:

Problem: service.py er 395 linjer.

Handling: Flyt logikken fra service.py over i de eksisterende (og tomme?) handlers.py (til Querys som GetDirectoryListingQuery).

Refaktorér storage:

Problem: storage_monitor.py er 396 linjer.

Handling: Opret commands.py, queries.py og handlers.py i app/domains/storage/.

Commands: Opret TriggerStorageCheckCommand. Flyt logikken fra trigger_immediate_check til en ny TriggerStorageCheckCommandHandler.

Queries: Opret GetStorageInfoQuery og GetOverallStorageStatusQuery. Flyt logikken fra get_source_info, get_destination_info, get_overall_status til nye QueryHandler-klasser.

Oprydning: StorageMonitorService er nu kun en baggrunds-worker, der kører _monitoring_loop.