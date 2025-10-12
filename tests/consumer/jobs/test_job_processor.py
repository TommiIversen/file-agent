"""
Simple tests for JobProcessor orchestrator - follows 2:1 line ratio rule.

Tests pure orchestration workflow between services.
Max 40 lines for 207-line service.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.consumer.job_processor import JobProcessor
from app.services.consumer.job_models import ProcessResult


class TestJobProcessor:
    """Simple, focused tests for orchestration."""

    @patch('app.services.consumer.job_processor.JobSpaceManager')
    @patch('app.services.consumer.job_processor.JobFinalizationService')
    @patch('app.services.consumer.job_processor.JobFilePreparationService')
    @patch('app.services.consumer.job_processor.JobCopyExecutor')
    @patch('app.services.consumer.job_processor.OutputFolderTemplateEngine')
    def test_processor_initialization(self, mock_template, mock_executor, mock_prep, mock_final, mock_space):
        """Test that processor initializes all services."""
        settings = MagicMock()
        state_manager = AsyncMock()
        job_queue = AsyncMock()
        copy_strategy_factory = MagicMock()
        
        processor = JobProcessor(settings, state_manager, job_queue, copy_strategy_factory)
        
        # Verify all services were created
        mock_space.assert_called_once()
        mock_final.assert_called_once()
        mock_prep.assert_called_once()
        mock_executor.assert_called_once()
        assert processor.space_manager == mock_space.return_value

    def test_get_processor_info(self):
        """Test processor info includes all services."""
        with patch('app.services.consumer.job_processor.JobSpaceManager') as mock_space, \
             patch('app.services.consumer.job_processor.JobFinalizationService') as mock_final, \
             patch('app.services.consumer.job_processor.JobFilePreparationService') as mock_prep, \
             patch('app.services.consumer.job_processor.JobCopyExecutor') as mock_executor, \
             patch('app.services.consumer.job_processor.OutputFolderTemplateEngine'):
            
            settings = MagicMock()
            processor = JobProcessor(settings, AsyncMock(), AsyncMock(), MagicMock())
            
            info = processor.get_processor_info()
            
            assert "space_manager" in info
            assert "finalization_service" in info
            assert "file_preparation_service" in info
            assert "copy_executor" in info