"""
Simple tests for JobProcessor orchestrator - follows 2:1 line ratio rule.

Tests pure orchestration workflow between services.
Max 40 lines for 207-line service.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.consumer.job_processor import JobProcessor


class TestJobProcessor:
    """Simple, focused tests for orchestration."""

    @patch("app.services.consumer.job_processor.JobSpaceManager")
    @patch("app.services.consumer.job_processor.JobFinalizationService")
    @patch("app.services.consumer.job_processor.JobFilePreparationService")
    @patch("app.services.consumer.job_processor.JobCopyExecutor")
    @patch("app.services.consumer.job_processor.OutputFolderTemplateEngine")
    def test_processor_initialization(
        self, _mock_template, mock_executor, mock_prep, mock_final, mock_space
    ):
        """Test that processor initializes all services."""
        settings = MagicMock()
        file_repository = AsyncMock()
        event_bus = AsyncMock()
        job_queue = AsyncMock()
        copy_strategy = MagicMock()

        processor = JobProcessor(
            settings, file_repository, event_bus, job_queue, copy_strategy
        )

        # Verify all services were created
        mock_space.assert_called_once()
        mock_final.assert_called_once()
        mock_prep.assert_called_once()
        mock_executor.assert_called_once()
        assert processor.space_manager == mock_space.return_value

    def test_get_processor_info(self):
        """Test processor info includes all services."""
        with (
            patch("app.services.consumer.job_processor.JobSpaceManager"),
            patch("app.services.consumer.job_processor.JobFinalizationService"),
            patch("app.services.consumer.job_processor.JobFilePreparationService"),
            patch("app.services.consumer.job_processor.JobCopyExecutor"),
            patch("app.services.consumer.job_processor.OutputFolderTemplateEngine"),
        ):
            settings = MagicMock()
            file_repository = AsyncMock()
            event_bus = AsyncMock()
            job_queue = AsyncMock()
            copy_strategy = MagicMock()
            processor = JobProcessor(settings, file_repository, event_bus, job_queue, copy_strategy)

            info = processor.get_processor_info()

            assert "space_manager" in info
            assert "finalization_service" in info
            assert "file_preparation_service" in info
            assert "copy_executor" in info
