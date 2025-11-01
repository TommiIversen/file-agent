import asyncio
import logging
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

# Importer de klasser, vi skal teste og mocke
from app.core.file_state_machine import FileStateMachine
from app.core.file_repository import FileRepository
from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import FileStatusChangedEvent
from app.core.exceptions import InvalidTransitionError
from app.models import TrackedFile, FileStatus

# Slå logning fra under tests for at holde output rent
logging.disable(logging.CRITICAL)


# --- Fixtures (Vores Test-Setup) ---

@pytest.fixture
def mock_repository() -> AsyncMock:
    """Opretter en "falsk" (mock) FileRepository for hver test."""
    return AsyncMock(spec=FileRepository)

@pytest.fixture
def mock_event_bus() -> AsyncMock:
    """Opretter en "falsk" (mock) EventBus for hver test."""
    return AsyncMock(spec=DomainEventBus)

@pytest.fixture
def state_machine(mock_repository: AsyncMock, mock_event_bus: AsyncMock) -> FileStateMachine:
    """Opretter en ny instans af vores FileStateMachine med de falske afhængigheder."""
    return FileStateMachine(
        file_repository=mock_repository,
        event_bus=mock_event_bus
    )

@pytest_asyncio.fixture
async def sample_file() -> TrackedFile:
    """Returnerer en "frisk" TrackedFile-objekt til hver test."""
    # Sørger for at rydde state mellem tests
    await asyncio.sleep(0) 
    return TrackedFile(
        file_path="/test/file.mxf",
        file_size=1024,
        status=FileStatus.DISCOVERED,
        error_message="Gammel Fejl" # Bruges til at teste om fejlbeskeder ryddes
    )

# --- Test Cases ---

@pytest.mark.asyncio
async def test_valid_transition(
    state_machine: FileStateMachine, 
    mock_repository: AsyncMock, 
    mock_event_bus: AsyncMock, 
    sample_file: TrackedFile
):
    """
    Tester "Happy Path": En gyldig status-overgang.
    """
    # Arrange: Sæt start-status og fortæl mock'en, hvad den skal returnere
    sample_file.status = FileStatus.DISCOVERED
    mock_repository.get_by_id.return_value = sample_file
    
    # Act: Udfør overgangen
    await state_machine.transition(file_id=sample_file.id, new_status=FileStatus.READY)
    
    # Giv event loop'en en chance til at køre den task, som 'create_task' oprettede
    await asyncio.sleep(0) 

    # Assert:
    
    # 1. Blev filen hentet?
    mock_repository.get_by_id.assert_called_once_with(sample_file.id)
    
    # 2. Blev filen opdateret i databasen?
    mock_repository.update.assert_called_once()
    updated_file_arg = mock_repository.update.call_args[0][0]
    assert isinstance(updated_file_arg, TrackedFile)
    assert updated_file_arg.status == FileStatus.READY
    assert updated_file_arg.error_message is None # Fejlen blev (korrekt) ryddet

    # 3. Blev der publiceret en event?
    mock_event_bus.publish.assert_called_once()
    event_arg = mock_event_bus.publish.call_args[0][0]
    assert isinstance(event_arg, FileStatusChangedEvent)
    assert event_arg.file_id == sample_file.id
    assert event_arg.old_status == FileStatus.DISCOVERED
    assert event_arg.new_status == FileStatus.READY

@pytest.mark.asyncio
async def test_invalid_transition(
    state_machine: FileStateMachine, 
    mock_repository: AsyncMock, 
    mock_event_bus: AsyncMock, 
    sample_file: TrackedFile
):
    """
    Tester, at en ugyldig overgang (f.eks. DISCOVERED -> IN_QUEUE) fejler.
    """
    # Arrange
    sample_file.status = FileStatus.DISCOVERED
    mock_repository.get_by_id.return_value = sample_file
    
    # Act & Assert: Tjek at den korrekte exception bliver kastet
    with pytest.raises(InvalidTransitionError) as e:
        await state_machine.transition(file_id=sample_file.id, new_status=FileStatus.IN_QUEUE)
        
    # Assert (at fejlen er informativ)
    assert "Discovered" in str(e.value)
    assert "InQueue" in str(e.value)
    
    # Assert (at intet blev gemt eller publiceret)
    mock_repository.update.assert_not_called()
    mock_event_bus.publish.assert_not_called()

@pytest.mark.asyncio
async def test_file_not_found(state_machine: FileStateMachine, mock_repository: AsyncMock):
    """
    Tester, at vi får en ValueError, hvis filen ikke findes i repository.
    """
    # Arrange
    mock_repository.get_by_id.return_value = None
    
    # Act & Assert
    with pytest.raises(ValueError) as e:
        await state_machine.transition(file_id="non-existent-id", new_status=FileStatus.READY)
        
    assert "findes ikke" in str(e.value)

@pytest.mark.asyncio
async def test_no_op_transition(
    state_machine: FileStateMachine, 
    mock_repository: AsyncMock, 
    mock_event_bus: AsyncMock, 
    sample_file: TrackedFile
):
    """
    Tester, at intet sker (ingen update, ingen event), hvis statussen er den samme.
    """
    # Arrange
    sample_file.status = FileStatus.READY
    mock_repository.get_by_id.return_value = sample_file
    
    # Act
    await state_machine.transition(file_id=sample_file.id, new_status=FileStatus.READY)
    
    # Giv event loop'en en chance (selvom intet burde ske)
    await asyncio.sleep(0)
    
    # Assert
    mock_repository.get_by_id.assert_called_once_with(sample_file.id)
    mock_repository.update.assert_not_called()
    mock_event_bus.publish.assert_not_called()

@pytest.mark.asyncio
async def test_transition_with_kwargs(
    state_machine: FileStateMachine, 
    mock_repository: AsyncMock, 
    sample_file: TrackedFile
):
    """
    Tester, at ekstra **kwargs (som error_message) bliver sat korrekt.
    """
    # Arrange
    sample_file.status = FileStatus.COPYING
    mock_repository.get_by_id.return_value = sample_file
    
    # Act
    test_error = "En specifik fejlbesked"
    await state_machine.transition(
        file_id=sample_file.id, 
        new_status=FileStatus.FAILED, 
        error_message=test_error,
        failed_at=datetime.now() # Test at vi også kan sætte tid
    )
    
    # Assert
    mock_repository.update.assert_called_once()
    updated_file = mock_repository.update.call_args[0][0]
    
    assert updated_file.status == FileStatus.FAILED
    assert updated_file.error_message == test_error
    assert updated_file.failed_at is not None

@pytest.mark.asyncio
async def test_automatic_timestamps(
    state_machine: FileStateMachine, 
    mock_repository: AsyncMock, 
    sample_file: TrackedFile
):
    """
    Tester, at timestamps (som completed_at) sættes automatisk.
    """
    # Arrange
    sample_file.status = FileStatus.COPYING
    sample_file.completed_at = None # Sørg for at den er tom
    mock_repository.get_by_id.return_value = sample_file
    
    # Act
    await state_machine.transition(file_id=sample_file.id, new_status=FileStatus.COMPLETED)
    
    # Assert
    mock_repository.update.assert_called_once()
    updated_file = mock_repository.update.call_args[0][0]
    
    assert updated_file.status == FileStatus.COMPLETED
    assert updated_file.completed_at is not None
    assert isinstance(updated_file.completed_at, datetime)