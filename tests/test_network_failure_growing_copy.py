"""
Test network failure handling through fail-fast detection
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.models import FileStatus, TrackedFile
from app.services.job_queue import JobQueueService
from app.services.state_manager import StateManager
from app.config import Settings

@pytest.mark.asyncio
class TestNetworkFailureHandling:
    
    @pytest.fixture
    def settings(self):
        return Settings(
            source_directory="c:\\temp_input",
            destination_directory="\\\\server\\share",
        )
    
    @pytest.fixture
    def mock_state_manager(self):
        mock = AsyncMock(spec=StateManager)
        return mock
    
    @pytest.fixture
    def job_queue(self, settings, mock_state_manager):
        return JobQueueService(
            settings=settings,
            state_manager=mock_state_manager,
            storage_monitor=None
        )
