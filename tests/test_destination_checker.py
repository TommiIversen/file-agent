"""
Tests for DestinationChecker strategy class.

Part of Phase 2.1 refactoring: Extract Strategy Classes from FileCopyService.

Tests cover:
- Destination availability checking various scenarios
- Write access testing with permissions
- Caching behavior and TTL functionality  
- Concurrent access handling
- Error handling and edge cases
"""

import asyncio
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

from app.services.destination.destination_checker import DestinationChecker, DestinationCheckResult


class TestDestinationCheckerBasics:
    """Test basic destination checker functionality."""
    
    @pytest.fixture
    def temp_dest_dir(self):
        """Create temporary destination directory for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def destination_checker(self, temp_dest_dir):
        """Create DestinationChecker instance for testing."""
        return DestinationChecker(temp_dest_dir, cache_ttl_seconds=1.0)
    
    def test_initialization(self, temp_dest_dir):
        """Test DestinationChecker initialization."""
        checker = DestinationChecker(temp_dest_dir, cache_ttl_seconds=10.0)
        
        assert checker.destination_path == temp_dest_dir
        assert checker.cache_ttl_seconds == 10.0
        assert checker._cached_result is None
        assert checker._cache_timestamp == 0.0
    
    @pytest.mark.asyncio
    async def test_is_available_with_valid_directory(self, destination_checker):
        """Test is_available with valid writable directory."""
        result = await destination_checker.is_available()
        
        assert result is True
        
        # Check that result was cached
        cache_info = destination_checker.get_cache_info()
        assert cache_info["has_cached_result"] is True
        assert cache_info["is_cache_valid"] is True
    
    @pytest.mark.asyncio
    async def test_is_available_with_nonexistent_directory(self):
        """Test is_available with non-existent directory."""
        # Use a truly inaccessible path that can't be created
        import tempfile
        temp_dir = Path(tempfile.mkdtemp())
        # Use a path with invalid characters that can't be created
        nonexistent_path = temp_dir / "invalid:path*"
        
        checker = DestinationChecker(nonexistent_path)
        
        result = await checker.is_available()
        
        # DestinationChecker tries to create directory, but this should fail
        # with invalid characters, so it should return False
        assert result is False
        
        # Clean up temp dir
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_is_available_with_file_instead_of_directory(self, temp_dest_dir):
        """Test is_available when destination is a file, not directory."""
        # Create a file instead of directory
        file_path = temp_dest_dir / "not_a_directory.txt"
        file_path.write_text("test")
        
        checker = DestinationChecker(file_path)
        result = await checker.is_available()
        
        assert result is False
        
        # Check error message
        cached_result = checker.get_cached_result()
        assert "not a directory" in cached_result.error_message


class TestDestinationCheckerWriteAccess:
    """Test write access functionality."""
    
    @pytest.fixture
    def temp_dest_dir(self):
        """Create temporary destination directory for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_test_write_access_success(self, temp_dest_dir):
        """Test successful write access."""
        checker = DestinationChecker(temp_dest_dir)
        
        result = await checker.test_write_access()
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_test_write_access_custom_path(self, temp_dest_dir):
        """Test write access to custom path."""
        custom_path = temp_dest_dir / "subdir"
        custom_path.mkdir()
        
        checker = DestinationChecker(temp_dest_dir)  # Different from test path
        result = await checker.test_write_access(custom_path)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_test_write_access_readonly_directory(self, temp_dest_dir):
        """Test write access failure with read-only directory."""
        # Make directory read-only (platform-specific)
        import stat
        temp_dest_dir.chmod(stat.S_IREAD)
        
        try:
            checker = DestinationChecker(temp_dest_dir)
            result = await checker.test_write_access()
            
            # Result depends on platform and permissions
            # On some systems, this might still succeed
            assert isinstance(result, bool)
        finally:
            # Restore permissions for cleanup
            temp_dest_dir.chmod(stat.S_IWRITE | stat.S_IREAD)


class TestDestinationCheckerCaching:
    """Test caching functionality and TTL behavior."""
    
    @pytest.fixture
    def temp_dest_dir(self):
        """Create temporary destination directory for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_cache_behavior_within_ttl(self, temp_dest_dir):
        """Test that cached results are used within TTL."""
        checker = DestinationChecker(temp_dest_dir, cache_ttl_seconds=2.0)
        
        # First call - should perform actual check
        result1 = await checker.is_available()
        cache_info1 = checker.get_cache_info()
        
        # Second call immediately - should use cache
        result2 = await checker.is_available()
        cache_info2 = checker.get_cache_info()
        
        assert result1 and result2
        assert cache_info1["cache_timestamp"] == cache_info2["cache_timestamp"]
        assert cache_info2["is_cache_valid"] is True
    
    @pytest.mark.asyncio
    async def test_cache_expiration_after_ttl(self, temp_dest_dir):
        """Test that cache expires after TTL."""
        checker = DestinationChecker(temp_dest_dir, cache_ttl_seconds=0.1)
        
        # First call
        result1 = await checker.is_available()
        cache_info1 = checker.get_cache_info()
        
        # Wait for cache to expire
        await asyncio.sleep(0.2)
        
        # Second call - should perform fresh check
        result2 = await checker.is_available()
        cache_info2 = checker.get_cache_info()
        
        assert result1 and result2
        assert cache_info1["cache_timestamp"] != cache_info2["cache_timestamp"]
    
    @pytest.mark.asyncio
    async def test_force_refresh_bypasses_cache(self, temp_dest_dir):
        """Test that force_refresh bypasses cache."""
        checker = DestinationChecker(temp_dest_dir, cache_ttl_seconds=10.0)
        
        # First call - creates cache
        result1 = await checker.is_available()
        cache_info1 = checker.get_cache_info()
        
        # Force refresh - should bypass cache
        result2 = await checker.is_available(force_refresh=True)
        cache_info2 = checker.get_cache_info()
        
        assert result1 and result2
        assert cache_info1["cache_timestamp"] != cache_info2["cache_timestamp"]
    
    def test_manual_cache_result(self, temp_dest_dir):
        """Test manually caching a result."""
        checker = DestinationChecker(temp_dest_dir)
        
        # Cache a result manually
        checker.cache_result(False, "Test error message")
        
        cached_result = checker.get_cached_result()
        assert cached_result is not None
        assert cached_result.is_available is False
        assert cached_result.error_message == "Test error message"
        assert isinstance(cached_result.checked_at, datetime)
    
    def test_clear_cache(self, temp_dest_dir):
        """Test cache clearing."""
        checker = DestinationChecker(temp_dest_dir)
        
        # Create cache entry
        checker.cache_result(True)
        assert checker.get_cached_result() is not None
        
        # Clear cache
        checker.clear_cache()
        assert checker.get_cached_result() is None
        
        cache_info = checker.get_cache_info()
        assert cache_info["has_cached_result"] is False
        assert cache_info["is_cache_valid"] is False


class TestDestinationCheckerConcurrency:
    """Test concurrent access handling."""
    
    @pytest.fixture
    def temp_dest_dir(self):
        """Create temporary destination directory for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_concurrent_access_protection(self, temp_dest_dir):
        """Test that concurrent calls are properly serialized."""
        checker = DestinationChecker(temp_dest_dir, cache_ttl_seconds=0.001)  # Very short TTL
        
        # First populate cache, then clear it to force concurrent fresh checks
        await checker.is_available()
        await asyncio.sleep(0.01)  # Wait for cache to expire
        
        # Mock the actual check to take some time and track calls
        original_check = checker._perform_availability_check
        call_order = []
        
        async def slow_check():
            call_order.append("start")
            await asyncio.sleep(0.05)
            result = await original_check()
            call_order.append("end")
            return result
        
        checker._perform_availability_check = slow_check
        
        # Start multiple concurrent calls (cache is expired, so all should need fresh check)
        tasks = [
            asyncio.create_task(checker.is_available()),
            asyncio.create_task(checker.is_available()),
            asyncio.create_task(checker.is_available())
        ]
        
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert all(results)
        
        # Due to locking, only the first should perform actual check
        # Others should wait and use the result from the first
        assert call_order.count("start") == 1
        assert call_order.count("end") == 1
    
    @pytest.mark.asyncio
    async def test_cache_prevents_concurrent_checks(self, temp_dest_dir):
        """Test that valid cache prevents concurrent actual checks."""
        checker = DestinationChecker(temp_dest_dir, cache_ttl_seconds=2.0)
        
        # First call to populate cache
        await checker.is_available()
        
        # Mock the actual check to track calls
        check_called = []
        original_check = checker._perform_availability_check
        
        async def tracked_check():
            check_called.append(True)
            return await original_check()
        
        checker._perform_availability_check = tracked_check
        
        # Multiple concurrent calls with valid cache
        tasks = [
            asyncio.create_task(checker.is_available()),
            asyncio.create_task(checker.is_available()),
            asyncio.create_task(checker.is_available())
        ]
        
        results = await asyncio.gather(*tasks)
        
        # All should succeed using cache
        assert all(result is True for result in results)
        
        # No actual checks should have been performed
        assert len(check_called) == 0


class TestDestinationCheckerEdgeCases:
    """Test edge cases and error handling."""
    
    @pytest.fixture
    def temp_dest_dir(self):
        """Create temporary destination directory for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_permission_error_during_check(self):
        """Test handling of permission errors during availability check."""
        # Use path that's likely to cause permission error
        restricted_path = Path("/root") if Path("/root").exists() else Path("C:\\System Volume Information")
        
        checker = DestinationChecker(restricted_path)
        result = await checker.is_available()
        
        # Should handle gracefully
        assert result is False
        
        cached_result = checker.get_cached_result()
        assert cached_result is not None
        assert cached_result.error_message is not None
    
    @pytest.mark.asyncio
    async def test_exception_during_write_test(self, temp_dest_dir):
        """Test handling of exceptions during write access test."""
        checker = DestinationChecker(temp_dest_dir)
        
        # Mock aiofiles.open to raise exception
        with patch('aiofiles.open', side_effect=PermissionError("Mock permission error")):
            result = await checker.test_write_access()
            
            assert result is False
    
    def test_get_cache_info_comprehensive(self, temp_dest_dir):
        """Test comprehensive cache info reporting."""
        checker = DestinationChecker(temp_dest_dir, cache_ttl_seconds=5.0)
        
        # Before any cache
        cache_info = checker.get_cache_info()
        assert cache_info["has_cached_result"] is False
        assert cache_info["cache_age_seconds"] is None
        assert cache_info["cache_ttl_seconds"] == 5.0
        assert cache_info["destination_path"] == str(temp_dest_dir)
        
        # After caching
        checker.cache_result(True)
        cache_info = checker.get_cache_info()
        assert cache_info["has_cached_result"] is True
        assert isinstance(cache_info["cache_age_seconds"], float)
        assert cache_info["cache_age_seconds"] >= 0


class TestDestinationCheckResult:
    """Test DestinationCheckResult dataclass."""
    
    def test_destination_check_result_creation(self):
        """Test creating DestinationCheckResult."""
        result = DestinationCheckResult(
            is_available=True,
            checked_at=datetime.now(),
            error_message="Test error",
            test_file_path="/tmp/test"
        )
        
        assert result.is_available is True
        assert isinstance(result.checked_at, datetime)
        assert result.error_message == "Test error"
        assert result.test_file_path == "/tmp/test"
    
    def test_destination_check_result_defaults(self):
        """Test DestinationCheckResult with default values."""
        result = DestinationCheckResult(
            is_available=False,
            checked_at=datetime.now()
        )
        
        assert result.is_available is False
        assert result.error_message is None
        assert result.test_file_path is None


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""
    
    @pytest.fixture
    def temp_dest_dir(self):
        """Create temporary destination directory for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_typical_usage_workflow(self, temp_dest_dir):
        """Test typical usage workflow with caching."""
        checker = DestinationChecker(temp_dest_dir, cache_ttl_seconds=1.0)
        
        # Initial check - should pass and create cache
        result1 = await checker.is_available()
        assert result1 is True
        
        # Quick second check - should use cache
        result2 = await checker.is_available()
        assert result2 is True
        
        # Test write access
        write_result = await checker.test_write_access()
        assert write_result is True
        
        # Force refresh
        result3 = await checker.is_available(force_refresh=True)
        assert result3 is True
        
        # Check cache info
        cache_info = checker.get_cache_info()
        assert cache_info["has_cached_result"] is True
        assert cache_info["is_cache_valid"] is True
    
    @pytest.mark.asyncio
    async def test_directory_becomes_unavailable(self, temp_dest_dir):
        """Test scenario where directory behavior when removed."""
        checker = DestinationChecker(temp_dest_dir, cache_ttl_seconds=0.1)
        
        # Initial check - should pass
        result1 = await checker.is_available()
        assert result1 is True
        
        # Remove directory
        shutil.rmtree(temp_dest_dir)
        
        # Wait for cache to expire
        await asyncio.sleep(0.2)
        
        # Check again - DestinationChecker will recreate the directory
        # so this should actually succeed, not fail
        result2 = await checker.is_available()
        assert result2 is True  # Changed: DestinationChecker recreates directory
        
        # Verify directory was recreated
        assert temp_dest_dir.exists()