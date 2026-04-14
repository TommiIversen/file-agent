import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Set, Optional

from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import FileStatusChangedEvent
from app.core.protocols import FileRepositoryProtocol
from app.models import FileStatus, TrackedFile
from app.core.exceptions import InvalidTransitionError


class FileStateMachine:
    """
    Central "dørmand" for alle filstatus-overgange.

    Dette er den ENESTE klasse i systemet, der må:
    1. Validere en status-overgang.
    2. Ændre en TrackedFile's .status felt.
    3. Gemme ændringen til FileRepository.
    4. Publicere FileStatusChangedEvent.

    Dette sikrer, at alle statusændringer er atomare og gyldige.
    """

    _pending_tasks: set[asyncio.Task] = set()

    def __init__(
        self,
        file_repository: FileRepositoryProtocol,
        event_bus: DomainEventBus,
    ):
        self._repository = file_repository
        self._event_bus = event_bus
        # Denne lås beskytter mod race conditions, 
        # hvor to tasks forsøger at ændre den *samme* fil samtidig.
        self._lock = asyncio.Lock()
        
        # Definerer alle lovlige overgange i systemet
        self._transitions: Dict[FileStatus, Set[FileStatus]] = {
            FileStatus.DISCOVERED: {
                FileStatus.READY,
                FileStatus.GROWING,
                FileStatus.REMOVED,
            },
            FileStatus.GROWING: {
                FileStatus.READY_TO_START_GROWING,
                FileStatus.READY,
                FileStatus.REMOVED,
            },
            FileStatus.READY_TO_START_GROWING: {
                FileStatus.IN_QUEUE,
                FileStatus.WAITING_FOR_NETWORK,
                FileStatus.REMOVED,
            },
            FileStatus.READY: {
                FileStatus.IN_QUEUE,
                FileStatus.WAITING_FOR_NETWORK,
                FileStatus.REMOVED,
            },
            FileStatus.IN_QUEUE: {
                FileStatus.COPYING,
                FileStatus.GROWING_COPY,
                FileStatus.READY, # Kan "bounces" tilbage
                FileStatus.WAITING_FOR_NETWORK,
            },
            FileStatus.COPYING: {
                FileStatus.COMPLETED,
                FileStatus.COMPLETED_DELETE_FAILED,
                FileStatus.FAILED,
                FileStatus.WAITING_FOR_NETWORK,
            },
            FileStatus.GROWING_COPY: {
                FileStatus.COPYING, 
                FileStatus.FAILED,
                FileStatus.WAITING_FOR_NETWORK,
            },
            FileStatus.WAITING_FOR_NETWORK: {
                FileStatus.READY, 
                FileStatus.READY_TO_START_GROWING,
                FileStatus.DISCOVERED, # Kan også gen-scannes
            },
            FileStatus.WAITING_FOR_SPACE: {
                FileStatus.READY, # Når en retry-timer udløber
            },
            FileStatus.FAILED: {
                FileStatus.READY, 
                FileStatus.DISCOVERED, 
            },
            FileStatus.SPACE_ERROR: {
                FileStatus.READY, 
            },
            FileStatus.COMPLETED: {
                FileStatus.DISCOVERED, 
            },
            FileStatus.COMPLETED_DELETE_FAILED: {
                FileStatus.DISCOVERED, 
            },
            FileStatus.REMOVED: {
                FileStatus.DISCOVERED, 
            },
        }
        logging.info("FileStateMachine initialiseret med %s overgangsregler", len(self._transitions))

    async def transition(
        self,
        *, # Force all parameters to be keyword-only
        file_id: str,
        new_status: FileStatus,
        **kwargs
    ) -> TrackedFile:
        """
        Udfører en status-overgang atomisk og publicerer en event.
        
        Args:
            file_id: ID på filen, der skal transitioneres (keyword-only).
            new_status: Den ønskede nye status (keyword-only).
            **kwargs: Valgfri felter, der skal opdateres (f.eks. error_message).

        Usage:
            await state_machine.transition(
                file_id="abc123",
                new_status=FileStatus.COMPLETED
            )

        Returns:
            Det opdaterede TrackedFile-objekt.

        Raises:
            InvalidTransitionError: Hvis overgangen ikke er tilladt.
            ValueError: Hvis filen ikke findes.
            TypeError: Hvis positional arguments anvendes.
        """
        
        event_to_publish: Optional[FileStatusChangedEvent] = None

        async with self._lock:
            # --- START AF KRITISK SEKTION ---
            # (Kun én task ad gangen må køre denne kode)

            # 1. GET (Friskeste data)
            tracked_file = await self._repository.get_by_id(file_id)
            if not tracked_file:
                raise ValueError(f"Fil med ID {file_id} findes ikke.")

            old_status = tracked_file.status

            # 2. VALIDATE
            if new_status == old_status:
                # Allow progress updates even if status doesn't change
                # Check if any other fields are being updated
                has_updates = any(
                    hasattr(tracked_file, key) and getattr(tracked_file, key) != value 
                    for key, value in kwargs.items()
                )
                if not has_updates:
                    return tracked_file # No changes at all
                # Continue with update if there are field changes (like progress)

            allowed_transitions = self._transitions.get(old_status, set())
            if new_status != old_status and new_status not in allowed_transitions:
                raise InvalidTransitionError(
                    tracked_file.file_path, old_status.value, new_status.value
                )

            # 3. MODIFY (Anvend ændringer)
            status_changed = new_status != old_status
            if status_changed:
                logging.info(f"Transition: {tracked_file.file_path} | {old_status.value} -> {new_status.value}")
            tracked_file.status = new_status
            
            # 3a. Ryd altid gamle fejl som standard på ENHVER overgang
            tracked_file.error_message = None 
                
            # 3b. Anvend nye værdier (dette vil OVERSKRIVE 'None', hvis 'error_message' er i kwargs)
            for key, value in kwargs.items():
                if hasattr(tracked_file, key):
                    setattr(tracked_file, key, value)
            
            # 3c. Sæt automatiske timestamps
            if new_status == FileStatus.COMPLETED and not tracked_file.completed_at:
                tracked_file.completed_at = datetime.now(timezone.utc)
            elif new_status == FileStatus.FAILED and not tracked_file.failed_at:
                tracked_file.failed_at = datetime.now(timezone.utc)

            # 4. SAVE (Atomisk opdatering)
            await self._repository.update(tracked_file)

            # 5. FORBERED ANNONCERING
            event_to_publish = None
            if status_changed:
                event_to_publish = FileStatusChangedEvent(
                    file_id=tracked_file.id,
                    file_path=tracked_file.file_path,
                    old_status=old_status,
                    new_status=new_status,
                    error_message=tracked_file.error_message,
                    timestamp=datetime.now(timezone.utc)
                )
            
            # --- SLUT AF KRITISK SEKTION ---
        
        # 6. ANNOUNCE (Fire and Forget with reference tracking)
        # Sker UDEN FOR låsen, så vi ikke blokerer andre
        # state-ændringer, mens vi venter på langsomme subscribers.
        if event_to_publish:
            task = asyncio.create_task(self._event_bus.publish(event_to_publish))
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)

        return tracked_file