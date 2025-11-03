




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