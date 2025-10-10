"""
Tests for Copy Strategy Factory (Phase 3.3).

Test coverage for CopyStrategyFactory including:
- Strategy selection logic based on file characteristics
- ExecutorConfig generation with optimal settings
- Progress callback creation and optimization
- Growing vs normal file handling
- Large file optimization
- Factory information and capabilities
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from app.config import Settings
from app.models import TrackedFile, FileStatus
from app.services.state_manager import StateManager
from app.services.copy.copy_strategy_factory import CopyStrategyFactory, ExecutorConfig
from app.services.copy.file_copy_executor import CopyProgress


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    settings = Mock(spec=Settings)
    settings.use_temporary_file = True
    settings.enable_growing_file_support = True
    settings.copy_progress_update_interval = 2
    settings.growing_file_chunk_size_kb = 32
    return settings


@pytest.fixture
def mock_state_manager():
    """Create mock state manager."""
    state_manager = Mock(spec=StateManager)
    state_manager.update_file_status = AsyncMock()
    return state_manager


@pytest.fixture
def copy_strategy_factory(mock_settings, mock_state_manager):
    """Create CopyStrategyFactory instance for testing."""
    return CopyStrategyFactory(mock_settings, mock_state_manager)


@pytest.fixture
def normal_tracked_file():
    """Create a normal (non-growing) tracked file."""
    return TrackedFile(
        file_path="/source/test.mxf",
        file_size=50 * 1024 * 1024,  # 50MB
        status=FileStatus.READY,
        is_growing_file=False,
        discovered_at=datetime.now()
    )


@pytest.fixture
def growing_tracked_file():
    """Create a growing tracked file."""
    return TrackedFile(
        file_path="/source/growing.mxv",
        file_size=200 * 1024 * 1024,  # 200MB
        status=FileStatus.READY,
        is_growing_file=True,
        growth_rate_mbps=5.0,
        discovered_at=datetime.now()
    )


@pytest.fixture
def large_tracked_file():
    """Create a large tracked file."""
    return TrackedFile(
        file_path="/source/large.mxf",
        file_size=500 * 1024 * 1024,  # 500MB
        status=FileStatus.READY,
        is_growing_file=False,
        discovered_at=datetime.now()
    )


class TestCopyStrategyFactoryBasics:
    """Test basic factory initialization and configuration."""
    
    def test_factory_initialization(self, mock_settings, mock_state_manager):
        """Test factory initializes correctly with dependencies."""
        factory = CopyStrategyFactory(mock_settings, mock_state_manager)
        
        assert factory.settings == mock_settings
        assert factory.state_manager == mock_state_manager
        assert factory.default_chunk_size == 64 * 1024
        assert factory.large_file_chunk_size == 256 * 1024
        assert factory.growing_file_chunk_size == 32 * 1024
        assert factory.large_file_threshold == 100 * 1024 * 1024
    
    def test_factory_initialization_with_custom_growing_chunk_size(self, mock_state_manager):
        """Test factory uses custom growing file chunk size from settings."""
        settings = Mock(spec=Settings)
        settings.use_temporary_file = True
        settings.enable_growing_file_support = True
        settings.copy_progress_update_interval = 2
        settings.growing_file_chunk_size_kb = 64  # Custom size
        
        factory = CopyStrategyFactory(settings, mock_state_manager)
        
        assert factory.growing_file_chunk_size == 64 * 1024
    
    def test_get_factory_info(self, copy_strategy_factory):
        """Test factory provides comprehensive configuration information."""
        info = copy_strategy_factory.get_factory_info()
        
        assert "default_chunk_size" in info
        assert "large_file_chunk_size" in info
        assert "growing_file_chunk_size" in info
        assert "large_file_threshold" in info
        assert "growing_file_support" in info
        assert "default_temp_file_usage" in info
        assert "available_strategies" in info
        
        assert info["default_chunk_size"] == 64 * 1024
        assert info["large_file_chunk_size"] == 256 * 1024
        assert info["growing_file_chunk_size"] == 32 * 1024
        assert info["growing_file_support"] is True
        assert isinstance(info["available_strategies"], list)
        assert len(info["available_strategies"]) >= 3
    
    def test_get_available_strategies(self, copy_strategy_factory):
        """Test factory returns available copy strategies."""
        strategies = copy_strategy_factory.get_available_strategies()
        
        assert isinstance(strategies, dict)
        assert "normal_temp" in strategies
        assert "normal_direct" in strategies
        assert "growing_stream" in strategies
        assert "growing_safe" in strategies  # Because growing support is enabled
        
        # Check strategy descriptions
        assert "temporary file" in strategies["normal_temp"].lower()
        assert "direct" in strategies["normal_direct"].lower()
        assert "streaming" in strategies["growing_stream"].lower()
    
    def test_get_available_strategies_no_growing_support(self, mock_state_manager):
        """Test strategies when growing file support is disabled."""
        settings = Mock(spec=Settings)
        settings.use_temporary_file = True
        settings.enable_growing_file_support = False
        settings.copy_progress_update_interval = 2
        settings.growing_file_chunk_size_kb = 32
        
        factory = CopyStrategyFactory(settings, mock_state_manager)
        strategies = factory.get_available_strategies()
        
        assert "normal_temp" in strategies
        assert "normal_direct" in strategies
        assert "growing_stream" in strategies
        assert "growing_safe" not in strategies  # Disabled


class TestExecutorConfigGeneration:
    """Test ExecutorConfig generation for different file types."""
    
    def test_executor_config_normal_file(self, copy_strategy_factory, normal_tracked_file):
        """Test config generation for normal files."""
        config = copy_strategy_factory.get_executor_config(normal_tracked_file)
        
        assert isinstance(config, ExecutorConfig)
        assert config.use_temp_file is True  # From settings
        assert config.chunk_size == 64 * 1024  # Default chunk size
        assert config.progress_update_interval == 2  # From settings
        assert config.strategy_name == "normal_temp"
        assert config.is_growing_file is False
        assert config.expected_file_size == normal_tracked_file.file_size
        assert config.copy_mode == "normal"
    
    def test_executor_config_growing_file(self, copy_strategy_factory, growing_tracked_file):
        """Test config generation for growing files."""
        config = copy_strategy_factory.get_executor_config(growing_tracked_file)
        
        assert isinstance(config, ExecutorConfig)
        assert config.use_temp_file is False  # Growing files don't use temp files
        assert config.chunk_size == 32 * 1024  # Growing file chunk size
        assert config.progress_update_interval == 1  # More frequent for growing files
        assert config.strategy_name == "growing_stream"
        assert config.is_growing_file is True
        assert config.expected_file_size == growing_tracked_file.file_size
        assert config.copy_mode == "growing"
    
    def test_executor_config_large_file(self, copy_strategy_factory, large_tracked_file):
        """Test config generation for large files."""
        config = copy_strategy_factory.get_executor_config(large_tracked_file)
        
        assert isinstance(config, ExecutorConfig)
        assert config.use_temp_file is True  # From settings
        assert config.chunk_size == 256 * 1024  # Large file chunk size
        assert config.progress_update_interval == 5  # Less frequent for large files
        assert config.strategy_name == "normal_temp"
        assert config.is_growing_file is False
        assert config.expected_file_size == large_tracked_file.file_size
        assert config.copy_mode == "large_file"
    
    def test_executor_config_direct_copy_setting(self, mock_state_manager, normal_tracked_file):
        """Test config when direct copy is preferred in settings."""
        settings = Mock(spec=Settings)
        settings.use_temporary_file = False  # Direct copy
        settings.enable_growing_file_support = True
        settings.copy_progress_update_interval = 2
        settings.growing_file_chunk_size_kb = 32
        
        factory = CopyStrategyFactory(settings, mock_state_manager)
        config = factory.get_executor_config(normal_tracked_file)
        
        assert config.use_temp_file is False
        assert config.strategy_name == "normal_direct"
    
    def test_executor_config_summary(self, copy_strategy_factory, normal_tracked_file):
        """Test ExecutorConfig summary generation."""
        config = copy_strategy_factory.get_executor_config(normal_tracked_file)
        summary = config.get_summary()
        
        assert "ExecutorConfig" in summary
        assert "strategy=normal_temp" in summary
        assert "mode=normal" in summary
        assert "temp_file=True" in summary
        assert f"chunk_size={64 * 1024}" in summary
        assert "growing=False" in summary


class TestTempFileDecisions:
    """Test temporary file usage decisions."""
    
    def test_should_use_temp_file_normal_file(self, copy_strategy_factory, normal_tracked_file):
        """Test temp file decision for normal files."""
        result = copy_strategy_factory.should_use_temp_file(normal_tracked_file)
        assert result is True  # From settings
    
    def test_should_use_temp_file_growing_file(self, copy_strategy_factory, growing_tracked_file):
        """Test temp file decision for growing files."""
        result = copy_strategy_factory.should_use_temp_file(growing_tracked_file)
        assert result is False  # Growing files don't use temp files
    
    def test_should_use_temp_file_disabled_growing_support(self, mock_state_manager, growing_tracked_file):
        """Test temp file decision when growing support is disabled."""
        settings = Mock(spec=Settings)
        settings.use_temporary_file = True
        settings.enable_growing_file_support = False  # Disabled
        settings.copy_progress_update_interval = 2
        settings.growing_file_chunk_size_kb = 32
        
        factory = CopyStrategyFactory(settings, mock_state_manager)
        result = factory.should_use_temp_file(growing_tracked_file)
        
        assert result is True  # Falls back to normal file behavior


class TestProgressCallbacks:
    """Test progress callback creation and functionality."""
    
    @pytest.mark.asyncio
    async def test_normal_file_progress_callback(self, copy_strategy_factory, normal_tracked_file, mock_state_manager):
        """Test progress callback for normal files."""
        callback = copy_strategy_factory.get_progress_callback(normal_tracked_file)
        
        # Test callback execution
        progress = CopyProgress(
            bytes_copied=25 * 1024 * 1024,  # 25MB
            total_bytes=50 * 1024 * 1024,   # 50MB
            elapsed_seconds=10.0,
            current_rate_bytes_per_sec=2.5 * 1024 * 1024  # 2.5 MB/s
        )
        
        await callback(progress)
        
        # Verify state manager was called with correct parameters
        mock_state_manager.update_file_status.assert_called_once()
        call_args = mock_state_manager.update_file_status.call_args
        
        assert call_args[0][0] == normal_tracked_file.file_path
        assert call_args[0][1] == FileStatus.COPYING
        assert call_args[1]["copy_progress"] == 50.0  # 50% progress
        assert call_args[1]["bytes_copied"] == 25 * 1024 * 1024
        assert abs(call_args[1]["copy_speed_mbps"] - 2.5) < 0.1
    
    @pytest.mark.asyncio
    async def test_growing_file_progress_callback(self, copy_strategy_factory, growing_tracked_file, mock_state_manager):
        """Test progress callback for growing files."""
        callback = copy_strategy_factory.get_progress_callback(growing_tracked_file)
        
        # Test callback execution
        progress = CopyProgress(
            bytes_copied=100 * 1024 * 1024,  # 100MB
            total_bytes=200 * 1024 * 1024,   # 200MB (may be growing)
            elapsed_seconds=20.0,
            current_rate_bytes_per_sec=5.0 * 1024 * 1024  # 5 MB/s
        )
        
        await callback(progress)
        
        # Verify state manager was called with growing copy status
        mock_state_manager.update_file_status.assert_called_once()
        call_args = mock_state_manager.update_file_status.call_args
        
        assert call_args[0][0] == growing_tracked_file.file_path
        assert call_args[0][1] == FileStatus.GROWING_COPY
        assert call_args[1]["copy_progress"] == 50.0  # 50% progress
        assert call_args[1]["bytes_copied"] == 100 * 1024 * 1024
        assert call_args[1]["file_size"] == 200 * 1024 * 1024  # Updated file size
        assert abs(call_args[1]["copy_speed_mbps"] - 5.0) < 0.1
    
    @pytest.mark.asyncio
    async def test_progress_callback_error_handling(self, copy_strategy_factory, normal_tracked_file, mock_state_manager):
        """Test progress callback error handling."""
        # Make state manager raise an exception
        mock_state_manager.update_file_status.side_effect = Exception("State update failed")
        
        callback = copy_strategy_factory.get_progress_callback(normal_tracked_file)
        progress = CopyProgress(
            bytes_copied=10 * 1024 * 1024,
            total_bytes=50 * 1024 * 1024,
            elapsed_seconds=5.0,
            current_rate_bytes_per_sec=2.0 * 1024 * 1024
        )
        
        # Should not raise exception - error should be logged
        with patch.object(copy_strategy_factory._logger, 'warning') as mock_warning:
            await callback(progress)
            
            # Verify logger warning was called
            mock_warning.assert_called_once()
            call_args = mock_warning.call_args[0][0]
            assert "Progress callback error" in call_args
            assert normal_tracked_file.file_path in call_args


class TestStrategySelection:
    """Test strategy selection logic and edge cases."""
    
    def test_strategy_selection_normal_file(self, copy_strategy_factory, normal_tracked_file):
        """Test strategy selection for normal files."""
        config = copy_strategy_factory.get_executor_config(normal_tracked_file)
        assert config.strategy_name == "normal_temp"
        assert not config.is_growing_file
    
    def test_strategy_selection_growing_file(self, copy_strategy_factory, growing_tracked_file):
        """Test strategy selection for growing files."""
        config = copy_strategy_factory.get_executor_config(growing_tracked_file)
        assert config.strategy_name == "growing_stream"
        assert config.is_growing_file
    
    def test_strategy_selection_growing_disabled(self, mock_state_manager, growing_tracked_file):
        """Test strategy selection when growing file support is disabled."""
        settings = Mock(spec=Settings)
        settings.use_temporary_file = True
        settings.enable_growing_file_support = False  # Disabled
        settings.copy_progress_update_interval = 2
        settings.growing_file_chunk_size_kb = 32
        
        factory = CopyStrategyFactory(settings, mock_state_manager)
        config = factory.get_executor_config(growing_tracked_file)
        
        # Should fall back to normal strategy even for growing files
        assert config.strategy_name == "normal_temp"
        assert not config.is_growing_file
    
    def test_chunk_size_optimization(self, copy_strategy_factory):
        """Test chunk size optimization for different file sizes."""
        # Small file
        small_file = TrackedFile(
            file_path="/source/small.mxf",
            file_size=10 * 1024 * 1024,  # 10MB
            status=FileStatus.READY,
            is_growing_file=False,
            discovered_at=datetime.now()
        )
        config = copy_strategy_factory.get_executor_config(small_file)
        assert config.chunk_size == 64 * 1024  # Default
        
        # Large file
        large_file = TrackedFile(
            file_path="/source/large.mxf",
            file_size=500 * 1024 * 1024,  # 500MB
            status=FileStatus.READY,
            is_growing_file=False,
            discovered_at=datetime.now()
        )
        config = copy_strategy_factory.get_executor_config(large_file)
        assert config.chunk_size == 256 * 1024  # Large file optimized
        
        # Growing file
        growing_file = TrackedFile(
            file_path="/source/growing.mxv",
            file_size=200 * 1024 * 1024,  # 200MB
            status=FileStatus.READY,
            is_growing_file=True,
            discovered_at=datetime.now()
        )
        config = copy_strategy_factory.get_executor_config(growing_file)
        assert config.chunk_size == 32 * 1024  # Growing file optimized
    
    def test_progress_interval_optimization(self, copy_strategy_factory):
        """Test progress update interval optimization."""
        # Normal file
        normal_file = TrackedFile(
            file_path="/source/normal.mxf",
            file_size=50 * 1024 * 1024,  # 50MB
            status=FileStatus.READY,
            is_growing_file=False,
            discovered_at=datetime.now()
        )
        config = copy_strategy_factory.get_executor_config(normal_file)
        assert config.progress_update_interval == 2  # From settings
        
        # Large file
        large_file = TrackedFile(
            file_path="/source/large.mxf",
            file_size=500 * 1024 * 1024,  # 500MB
            status=FileStatus.READY,
            is_growing_file=False,
            discovered_at=datetime.now()
        )
        config = copy_strategy_factory.get_executor_config(large_file)
        assert config.progress_update_interval == 5  # Less frequent for large files
        
        # Growing file
        growing_file = TrackedFile(
            file_path="/source/growing.mxv",
            file_size=200 * 1024 * 1024,  # 200MB
            status=FileStatus.READY,
            is_growing_file=True,
            discovered_at=datetime.now()
        )
        config = copy_strategy_factory.get_executor_config(growing_file)
        assert config.progress_update_interval == 1  # More frequent for growing files


class TestCopyProgressDataclass:
    """Test CopyProgress integration with factory callbacks."""
    
    def test_copy_progress_properties(self):
        """Test CopyProgress property calculations."""
        progress = CopyProgress(
            bytes_copied=50 * 1024 * 1024,  # 50MB
            total_bytes=100 * 1024 * 1024,  # 100MB
            elapsed_seconds=20.0,
            current_rate_bytes_per_sec=2.5 * 1024 * 1024  # 2.5 MB/s
        )
        
        assert progress.progress_percent == 50.0
        assert progress.progress_percent_int == 50
        assert progress.remaining_bytes == 50 * 1024 * 1024
        assert progress.estimated_remaining_seconds == 20.0  # 50MB / 2.5MB/s
    
    def test_copy_progress_edge_cases(self):
        """Test CopyProgress with edge case values."""
        # Zero total bytes
        progress = CopyProgress(
            bytes_copied=0,
            total_bytes=0,
            elapsed_seconds=0.0,
            current_rate_bytes_per_sec=0.0
        )
        assert progress.progress_percent == 0.0
        assert progress.remaining_bytes == 0
        assert progress.estimated_remaining_seconds == 0.0
        
        # Over 100% progress
        progress = CopyProgress(
            bytes_copied=120 * 1024 * 1024,
            total_bytes=100 * 1024 * 1024,
            elapsed_seconds=10.0,
            current_rate_bytes_per_sec=12.0 * 1024 * 1024
        )
        assert progress.progress_percent == 100.0  # Capped at 100
        assert progress.remaining_bytes == 0  # No negative values


class TestFactoryIntegration:
    """Test factory integration with other components."""
    
    def test_factory_logging_configuration(self, copy_strategy_factory):
        """Test factory creates appropriate logger."""
        assert copy_strategy_factory._logger.name == "app.strategy_factory"
    
    def test_factory_with_minimal_settings(self, mock_state_manager):
        """Test factory works with minimal settings configuration."""
        settings = Mock(spec=Settings)
        settings.use_temporary_file = False
        settings.enable_growing_file_support = False
        # Missing growing_file_chunk_size_kb and copy_progress_update_interval
        
        factory = CopyStrategyFactory(settings, mock_state_manager)
        
        # Should use defaults
        assert factory.growing_file_chunk_size == 32 * 1024  # Default from getattr
        
        # Should work with normal file
        normal_file = TrackedFile(
            file_path="/test.mxf",
            file_size=10 * 1024 * 1024,
            status=FileStatus.READY,
            is_growing_file=False,
            discovered_at=datetime.now()
        )
        
        config = factory.get_executor_config(normal_file)
        assert config.strategy_name == "normal_direct"
        assert not config.use_temp_file