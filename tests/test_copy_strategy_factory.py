"""
Simple tests for CopyStrategyFactory.

Clean test focusing on basic functionality.
"""

import pytest
from unittest.mock import Mock, AsyncMock

from app.config import Settings
from app.models import TrackedFile, FileStatus  
from app.services.state_manager import StateManager
from app.services.copy_strategies import CopyStrategyFactory


def test_basic_import():
    """Test that we can import everything we need."""
    assert CopyStrategyFactory is not None
    assert Settings is not None
    assert TrackedFile is not None


@pytest.fixture
def basic_settings():
    """Create basic settings for testing."""
    return Settings(
        source_directory="/test/source",
        destination_directory="/test/dest"
    )


@pytest.fixture 
def mock_state_manager():
    """Create mock state manager."""
    state_manager = Mock(spec=StateManager)
    state_manager.update_file_status = AsyncMock()
    return state_manager


class TestBasicFactoryCreation:
    """Test basic factory creation."""
    
    def test_can_create_factory(self, basic_settings, mock_state_manager):
        """Test that we can create a factory."""
        factory = CopyStrategyFactory(basic_settings, mock_state_manager)
        assert factory is not None
        
    def test_factory_has_basic_methods(self, basic_settings, mock_state_manager):
        """Test that factory has expected methods."""
        factory = CopyStrategyFactory(basic_settings, mock_state_manager)
        assert hasattr(factory, 'get_strategy')
        assert hasattr(factory, 'get_available_strategies')
