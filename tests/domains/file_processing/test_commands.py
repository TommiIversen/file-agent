"""
Lightweight tests for CQRS commands in file processing domain.

These tests verify the command structure and validation without complex dependencies.
"""

from datetime import datetime
from uuid import uuid4

from app.domains.file_processing.commands import QueueFileCommand, ProcessJobCommand
from app.domains.file_processing.consumer.job_models import QueueJob
from app.models import TrackedFile, FileStatus


class TestQueueFileCommand:
    """Test the QueueFileCommand structure and validation."""

    def test_queue_file_command_creation(self):
        """Test that QueueFileCommand can be created with valid TrackedFile."""
        tracked_file = TrackedFile(
            id=str(uuid4()),
            file_path="/test/file.mxf",
            file_size=1000000,
            status=FileStatus.READY,
            creation_time=datetime.now(),
            last_modified=datetime.now()
        )
        
        command = QueueFileCommand(tracked_file=tracked_file)
        
        assert command.tracked_file == tracked_file
        assert command.tracked_file.file_path == "/test/file.mxf"
        assert command.tracked_file.file_size == 1000000

    def test_queue_file_command_structure(self):
        """Test that QueueFileCommand has the expected structure."""
        tracked_file = TrackedFile(
            id=str(uuid4()),
            file_path="/test/file.mxf",
            file_size=1000000,
            status=FileStatus.READY,
            creation_time=datetime.now(),
            last_modified=datetime.now()
        )
        
        command = QueueFileCommand(tracked_file=tracked_file)
        
        # Verify the command structure
        assert hasattr(command, 'tracked_file')
        assert command.tracked_file == tracked_file
        assert command.tracked_file.file_path == "/test/file.mxf"
        assert command.tracked_file.file_size == 1000000


class TestProcessJobCommand:
    """Test the ProcessJobCommand structure and validation."""

    def test_process_job_command_creation(self):
        """Test that ProcessJobCommand can be created with valid QueueJob."""
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
        assert command.job.file_size == 2000000

    def test_process_job_command_structure(self):
        """Test that ProcessJobCommand has the expected structure."""
        queue_job = QueueJob(
            file_id=str(uuid4()),
            file_path="/test/job.mxf",
            file_size=2000000,
            creation_time=datetime.now(),
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now()
        )
        
        command = ProcessJobCommand(job=queue_job)
        
        # Verify the command structure
        assert hasattr(command, 'job')
        assert command.job == queue_job
        assert command.job.file_path == "/test/job.mxf"
        assert command.job.file_size == 2000000

    def test_job_data_consistency(self):
        """Test that job data remains consistent through command creation."""
        file_id = str(uuid4())
        creation_time = datetime.now()
        added_time = datetime.now()
        
        queue_job = QueueJob(
            file_id=file_id,
            file_path="/test/consistency.mxf",
            file_size=5000000,
            creation_time=creation_time,
            is_growing_at_queue_time=True,
            added_to_queue_at=added_time,
            retry_count=2
        )
        
        command = ProcessJobCommand(job=queue_job)
        
        # Verify all job attributes are preserved
        assert command.job.file_id == file_id
        assert command.job.creation_time == creation_time
        assert command.job.added_to_queue_at == added_time
        assert command.job.is_growing_at_queue_time is True
        assert command.job.retry_count == 2


class TestCommandDataFlow:
    """Test the data flow between TrackedFile → QueueJob → Command."""

    def test_tracked_file_to_queue_job_to_command_flow(self):
        """Test complete data flow from TrackedFile through QueueJob to ProcessJobCommand."""
        # Start with TrackedFile
        file_id = str(uuid4())
        tracked_file = TrackedFile(
            id=file_id,
            file_path="/test/flow.mxf",
            file_size=3000000,
            status=FileStatus.READY,
            creation_time=datetime.now(),
            last_modified=datetime.now()
        )
        
        # Create QueueJob from TrackedFile data  
        queue_job = QueueJob(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            file_size=tracked_file.file_size,
            creation_time=tracked_file.creation_time,
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now()
        )
        
        # Create commands
        queue_command = QueueFileCommand(tracked_file=tracked_file)
        process_command = ProcessJobCommand(job=queue_job)
        
        # Verify data consistency
        assert queue_command.tracked_file.id == file_id
        assert process_command.job.file_id == file_id
        assert queue_command.tracked_file.file_path == process_command.job.file_path
        assert queue_command.tracked_file.file_size == process_command.job.file_size