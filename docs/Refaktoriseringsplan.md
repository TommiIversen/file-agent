Handlingsplan: Implementering af Persistent Repository
Mål: At erstatte den flygtige (in-memory) FileRepository med en persistent SqliteFileRepository og optimere alle get_all()-kald til at bruge effektive SQL-forespørgsler.

Fase 1: Opdater In-Memory FileRepository-kontrakten
Mål: Tilføj nye, specifikke filtreringsmetoder til den eksisterende FileRepository, og opdater FileDiscoverySlice til at bruge dem. Dette isolerer refaktoreringen uden at ændre databasen endnu.

Opdater app/core/file_repository.py:

Handling: Tilføj de nye metoder (get_files_by_status, get_files_by_path, get_active_files_by_path). Deres implementation vil stadig iterere over dict'en – det er OK for nu.

Python

# app/core/file_repository.py

class FileRepository:
    # ... (eksisterende __init__, get_by_id, add, update, remove, count) ...

    async def get_all(self) -> List[TrackedFile]:
        """Get a list of all tracked files."""
        async with self._lock:
            return list(self._files_by_id.values())

    # --- NYE METODER TILFØJET I FASE 1 ---

    async def get_files_by_status(self, status: FileStatus) -> List[TrackedFile]:
        """Henter filer med en specifik status (In-Memory implementation)."""
        async with self._lock:
            return [
                f for f in self._files_by_id.values() 
                if f.status == status
            ]

    async def get_files_by_path(self, file_path: str) -> List[TrackedFile]:
        """Henter alle fil-objekter (aktive og inaktive) for en sti."""
        async with self._lock:
            return [
                f for f in self._files_by_id.values() 
                if f.file_path == file_path
            ]

    async def get_active_files_by_path(self, file_path: str, active_statuses: Set[FileStatus]) -> List[TrackedFile]:
        """Henter aktive filer for en sti (In-Memory implementation)."""
        async with self._lock:
            return [
                f for f in self._files_by_id.values() 
                if f.file_path == file_path and f.status in active_statuses
            ]

    async def get_files_needing_growth_monitoring(self, growth_statuses: Set[FileStatus]) -> List[TrackedFile]:
        """Henter filer til growth monitoring (In-Memory implementation)."""
        async with self._lock:
            return [
                f for f in self._files_by_id.values()
                if f.last_growth_check is not None and f.status in growth_statuses
            ]
Refaktorér app/domains/file_discovery/file_discovery_slice.py:

Handling: Opdater alle metoder, der kalder self._file_repository.get_all(), til at bruge de nye, specifikke metoder.

Refaktorér get_active_file_by_path:

FØR:

Python

all_files = await self._file_repository.get_all()
candidates = [
    f for f in all_files 
    if f.file_path == file_path and f.status in active_statuses
]
EFTER:

Python

candidates = await self._file_repository.get_active_files_by_path(
    file_path, active_statuses
)
Refaktorér get_current_file_for_path:

FØR:

Python

all_files = await self._file_repository.get_all()
candidates = [f for f in all_files if f.file_path == file_path]
EFTER:

Python

candidates = await self._file_repository.get_files_by_path(file_path)
Refaktorér get_files_by_status:

FØR:

Python

all_files = await self._file_repository.get_all()
for tracked_file in all_files:
    if tracked_file.status == status:
        # ... (filtreringslogik) ...
EFTER (som diskuteret):

Python

# Hent kun de relevante filer først
files_with_status = await self._file_repository.get_files_by_status(status)

# Kør derefter din prioriteringslogik på det mindre sæt
current_files = {}
for tracked_file in files_with_status:
    current = current_files.get(tracked_file.file_path)
    # ... (resten af din _is_more_current logik) ...
Refaktorér get_files_needing_growth_monitoring:

FØR:

Python

all_files = await self._file_repository.get_all()
# ... (filtrering i Python) ...
EFTER:

Python

growth_statuses = {
    FileStatus.DISCOVERED,
    FileStatus.GROWING,
    FileStatus.READY_TO_START_GROWING,
}
return await self._file_repository.get_files_needing_growth_monitoring(
    growth_statuses
)
Manuel Test (Fase 1 Udført):

Kør applikationen. Alt skal virke præcis som før. Du har nu forberedt din kodebase til en database-udskiftning.

Fase 2: Implementer og Udskift til SqliteFileRepository
Mål: Opret den nye SqliteFileRepository og udskift den i dependencies.py.

Installer Afhængigheder:

pip install sqlmodel aiosqlite

Definer Database-modellen:

Fil: app/models.py (eller en ny app/core/db_models.py)

Handling: Opret en SQLModel-version af din TrackedFile-model.

Python

from sqlmodel import SQLModel, Field, JSON, Column
from typing import Optional, Dict, Any
from datetime import datetime
from app.models import FileStatus, RetryInfo # Importer dine Pydantic-modeller

# Fortæl SQLModel, hvordan den skal håndtere custom Pydantic-typer
class PydanticJSONType(JSON):
    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is not None:
            return value.model_dump_json()
        return None

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is not None:
            return RetryInfo.model_validate_json(value)
        return None

class DBTrackedFile(SQLModel, table=True):
    __tablename__ = "trackedfile"

    # Spejl din Pydantic TrackedFile-model
    id: str = Field(primary_key=True)
    file_path: str = Field(index=True)
    status: FileStatus = Field(index=True)
    file_size: int = 0
    last_write_time: Optional[datetime] = None
    copy_progress: float = 0.0
    error_message: Optional[str] = None
    retry_count: int = 0
    discovered_at: datetime = Field(default_factory=datetime.now, index=True)
    creation_time: Optional[datetime] = Field(index=True)
    started_copying_at: Optional[datetime] = None
    completed_at: Optional[datetime] = Field(index=True)
    failed_at: Optional[datetime] = None
    space_error_at: Optional[datetime] = None
    destination_path: Optional[str] = None

    # ... (alle andre felter fra TrackedFile)

    # Gem komplekse Pydantic-objekter som JSON
    retry_info: Optional[RetryInfo] = Field(sa_column=Column(PydanticJSONType), default=None)
Opret SqliteFileRepository:

Fil: app/core/sqlite_file_repository.py (Ny fil)

Python

import logging
from typing import List, Optional, Set, Dict
from sqlmodel import SQLModel, create_async_engine, AsyncSession, select, func
from app.models import TrackedFile, FileStatus
from app.core.db_models import DBTrackedFile # Importer din nye DB-model

class SqliteFileRepository:
    """Persistent repository, der implementerer samme interface som FileRepository."""

    def __init__(self, db_url: str = "sqlite+aiosqlite:///file_agent_prod.db"):
        self._engine = create_async_engine(db_url)
        logging.info(f"SqliteFileRepository initialiseret med db: {db_url}")

    async def init_db(self):
        """Kaldes fra main.py lifespan for at oprette tabeller."""
        async with self._engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    async def get_by_id(self, file_id: str) -> Optional[TrackedFile]:
        async with AsyncSession(self._engine) as session:
            db_file = await session.get(DBTrackedFile, file_id)
            return TrackedFile.model_validate(db_file) if db_file else None

    async def get_all(self) -> List[TrackedFile]:
        async with AsyncSession(self._engine) as session:
            statement = select(DBTrackedFile)
            result = await session.execute(statement)
            return [TrackedFile.model_validate(f) for f in result.scalars().all()]

    async def add(self, tracked_file: TrackedFile) -> None:
        async with AsyncSession(self._engine) as session:
            db_file = DBTrackedFile.model_validate(tracked_file)
            session.add(db_file)
            await session.commit()

    async def update(self, tracked_file: TrackedFile) -> None:
        async with AsyncSession(self._engine) as session:
            db_file = DBTrackedFile.model_validate(tracked_file)
            await session.merge(db_file)
            await session.commit()

    async def remove(self, file_id: str) -> bool:
        async with AsyncSession(self._engine) as session:
            db_file = await session.get(DBTrackedFile, file_id)
            if db_file:
                await session.delete(db_file)
                await session.commit()
                return True
            return False

    async def count(self) -> int:
        async with AsyncSession(self._engine) as session:
            statement = select(func.count()).select_from(DBTrackedFile)
            result = await session.execute(statement)
            return result.scalar_one()

    # --- OPTIMEREDE METODER (IMPLEMENTERET MED SQL) ---

    async def get_files_by_status(self, status: FileStatus) -> List[TrackedFile]:
        async with AsyncSession(self._engine) as session:
            statement = select(DBTrackedFile).where(DBTrackedFile.status == status)
            result = await session.execute(statement)
            return [TrackedFile.model_validate(f) for f in result.scalars().all()]

    async def get_files_by_path(self, file_path: str) -> List[TrackedFile]:
        async with AsyncSession(self._engine) as session:
            statement = select(DBTrackedFile).where(DBTrackedFile.file_path == file_path)
            result = await session.execute(statement)
            return [TrackedFile.model_validate(f) for f in result.scalars().all()]

    async def get_active_files_by_path(self, file_path: str, active_statuses: Set[FileStatus]) -> List[TrackedFile]:
        async with AsyncSession(self._engine) as session:
            statement = select(DBTrackedFile).where(
                DBTrackedFile.file_path == file_path,
                DBTrackedFile.status.in_(active_statuses)
            )
            result = await session.execute(statement)
            return [TrackedFile.model_validate(f) for f in result.scalars().all()]

    async def get_files_needing_growth_monitoring(self, growth_statuses: Set[FileStatus]) -> List[TrackedFile]:
        async with AsyncSession(self._engine) as session:
            statement = select(DBTrackedFile).where(
                DBTrackedFile.last_growth_check.isnot(None),
                DBTrackedFile.status.in_(growth_statuses)
            )
            result = await session.execute(statement)
            return [TrackedFile.model_validate(f) for f in result.scalars().all()]

    async def get_status_counts(self) -> Dict[FileStatus, int]:
        """Bruger SQL GROUP BY til at tælle alle statusser."""
        async with AsyncSession(self._engine) as session:
            statement = (
                select(DBTrackedFile.status, func.count(DBTrackedFile.id))
                .group_by(DBTrackedFile.status)
            )
            result = await session.execute(statement)
            return {status: count for status, count in result}
Opdater app/dependencies.py (Den Store Udskiftning):

Handling: Byt FileRepository ud med SqliteFileRepository.

FØR:

Python

def get_file_repository() -> FileRepository:
    if "file_repository" not in _singletons:
        _singletons["file_repository"] = FileRepository()
    return _singletons["file_repository"]
EFTER:

Python

from app.core.sqlite_file_repository import SqliteFileRepository

def get_file_repository() -> SqliteFileRepository:
    if "file_repository" not in _singletons:
        _singletons["file_repository"] = SqliteFileRepository()
    return _singletons["file_repository"]
Opdater app/main.py (Initialiser Databasen):

Handling: Sørg for, at databasen og tabellerne oprettes ved opstart.

Python

# I app/main.py
from app.dependencies import get_file_repository

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... (din anden opstartslogik) ...

    # Initialiser databasen
    db_repo = get_file_repository()
    await db_repo.init_db()
    logging.info("Database tabeller initialiseret.")

    yield
    # ... (din nedlukningslogik) ...
Manuel Test (Fase 2 Udført):

Slet din gamle file_agent_prod.db-fil (hvis den findes).

Start applikationen. Verificer, at file_agent_prod.db oprettes.

Kør systemet. Verificer, at get_files_by_status-kald (som sker i FileDiscoverySlice) er meget hurtigere, især når UI'et loader statistik.





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