"""
Simple CQRS structure tests for file processing domain.

These tests verify command and model structure without async complexity.
"""

from datetime import datetime
from uuid import uuid4

from app.domains.file_processing.commands import QueueFileCommand, ProcessJobCommand
from app.domains.file_processing.consumer.job_models import QueueJob
from app.models import TrackedFile, FileStatus


class TestCommandStructure:
    """Test command structure and data integrity."""

    def test_queue_file_command_creation(self):
        """Test QueueFileCommand can be created with TrackedFile."""
        tracked_file = TrackedFile(
            id=str(uuid4()),
            file_path="/test/simple.mxf",
            file_size=1000000,
            status=FileStatus.READY,
            creation_time=datetime.now(),
            last_modified=datetime.now()
        )
        
        command = QueueFileCommand(tracked_file=tracked_file)
        
        assert command.tracked_file == tracked_file
        assert command.tracked_file.file_path == "/test/simple.mxf"

    def test_process_job_command_creation(self):
        """Test ProcessJobCommand can be created with QueueJob."""
        queue_job = QueueJob(
            file_id=str(uuid4()),
            file_path="/test/job.mxf",
            file_size=2000000,
            creation_time=datetime.now(),
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now()
        )
        
        command = ProcessJobCommand(job=queue_job)
        
        assert command.job == queue_job
        assert command.job.file_path == "/test/job.mxf"

    def test_data_consistency_flow(self):
        """Test data remains consistent from TrackedFile to ProcessJobCommand."""
        file_id = str(uuid4())
        
        # TrackedFile
        tracked_file = TrackedFile(
            id=file_id,
            file_path="/test/consistency.mxf",
            file_size=3000000,
            status=FileStatus.READY,
            creation_time=datetime.now(),
            last_modified=datetime.now()
        )
        
        # QueueJob (simulating what would be created from TrackedFile)
        queue_job = QueueJob(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            file_size=tracked_file.file_size,
            creation_time=tracked_file.creation_time,
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now()
        )
        
        # Commands
        queue_command = QueueFileCommand(tracked_file=tracked_file)
        process_command = ProcessJobCommand(job=queue_job)
        
        # Verify consistency
        assert queue_command.tracked_file.id == file_id
        assert process_command.job.file_id == file_id
        assert queue_command.tracked_file.file_path == process_command.job.file_path


class TestJobModels:
    """Test job model structure and behavior."""

    def test_queue_job_creation_with_all_fields(self):
        """Test QueueJob creation with all required fields."""
        now = datetime.now()
        creation_time = datetime.now()
        
        job = QueueJob(
            file_id=str(uuid4()),
            file_path="/test/full_job.mxf",
            file_size=5000000,
            creation_time=creation_time,
            is_growing_at_queue_time=True,
            added_to_queue_at=now,
            retry_count=2
        )
        
        assert job.file_size == 5000000
        assert job.is_growing_at_queue_time is True
        assert job.retry_count == 2
        assert job.creation_time == creation_time
        assert job.added_to_queue_at == now

    def test_queue_job_retry_functionality(self):
        """Test QueueJob retry tracking methods."""
        job = QueueJob(
            file_id=str(uuid4()),
            file_path="/test/retry.mxf",
            file_size=1000000,
            creation_time=datetime.now(),
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now()
        )
        
        # Initial state
        assert job.retry_count == 0
        assert job.last_retry_at is None
        assert job.last_error_message is None
        
        # After retry
        job.mark_retry("Test error")
        assert job.retry_count == 1
        assert job.last_retry_at is not None
        assert job.last_error_message == "Test error"

    def test_queue_job_priority_comparison(self):
        """Test QueueJob priority ordering based on creation time."""
        older_time = datetime(2024, 1, 1, 12, 0, 0)
        newer_time = datetime(2024, 1, 1, 13, 0, 0)
        
        older_job = QueueJob(
            file_id=str(uuid4()),
            file_path="/test/older.mxf",
            file_size=1000000,
            creation_time=older_time,
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now()
        )
        
        newer_job = QueueJob(
            file_id=str(uuid4()),
            file_path="/test/newer.mxf",
            file_size=1000000,
            creation_time=newer_time,
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now()
        )
        
        # Older files should have priority (return True for <)
        assert older_job < newer_job
        assert not (newer_job < older_job)


class TestCQRSStructuralIntegrity:
    """Test structural integrity of CQRS components."""

    def test_commands_are_dataclasses(self):
        """Test that our commands are proper dataclasses."""
        tracked_file = TrackedFile(
            id=str(uuid4()),
            file_path="/test/dataclass.mxf",
            file_size=1000000,
            status=FileStatus.READY,
            creation_time=datetime.now(),
            last_modified=datetime.now()
        )
        
        command = QueueFileCommand(tracked_file=tracked_file)
        
        # Should have dataclass behavior
        assert hasattr(command, '__dataclass_fields__')
        assert 'tracked_file' in command.__dataclass_fields__

    def test_models_have_required_attributes(self):
        """Test that our models have all required attributes for CQRS."""
        # TrackedFile
        tracked_file = TrackedFile(
            id=str(uuid4()),
            file_path="/test/attrs.mxf",
            file_size=1000000,
            status=FileStatus.READY,
            creation_time=datetime.now(),
            last_modified=datetime.now()
        )
        
        required_tracked_attrs = ['id', 'file_path', 'file_size', 'status', 'creation_time']
        for attr in required_tracked_attrs:
            assert hasattr(tracked_file, attr)
            assert getattr(tracked_file, attr) is not None
        
        # QueueJob
        queue_job = QueueJob(
            file_id=str(uuid4()),
            file_path="/test/attrs_job.mxf",
            file_size=2000000,
            creation_time=datetime.now(),
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now()
        )
        
        required_job_attrs = ['file_id', 'file_path', 'file_size', 'creation_time', 'added_to_queue_at']
        for attr in required_job_attrs:
            assert hasattr(queue_job, attr)
            assert getattr(queue_job, attr) is not None

    def test_command_immutability_principle(self):
        """Test that commands maintain data integrity (CQRS principle)."""
        tracked_file = TrackedFile(
            id=str(uuid4()),
            file_path="/test/immutable.mxf",
            file_size=1000000,
            status=FileStatus.READY,
            creation_time=datetime.now(),
            last_modified=datetime.now()
        )
        
        command = QueueFileCommand(tracked_file=tracked_file)
        original_file_path = command.tracked_file.file_path
        
        # The command should hold the same reference
        assert command.tracked_file is tracked_file
        assert command.tracked_file.file_path == original_file_path
        
        # Verify the command contains the data we expect
        assert command.tracked_file.file_size == 1000000
        assert command.tracked_file.status == FileStatus.READY