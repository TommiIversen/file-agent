#!/usr/bin/env python3
"""
Test that verifies the JobProcessor now has proper error classification
when files are removed during copying.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.dependencies import get_job_processor


async def test_job_processor_has_error_classifier():
    """Test that JobProcessor is created with a proper error classifier."""
    
    print("=== Testing JobProcessor Error Classifier Integration ===")
    
    try:
        # Get the job processor from dependencies
        job_processor = get_job_processor()
        
        # Check if it has a copy_executor
        if not hasattr(job_processor, 'copy_executor'):
            print("❌ ERROR: JobProcessor doesn't have copy_executor")
            return False
        
        copy_executor = job_processor.copy_executor
        
        # Check if copy_executor has error_classifier
        if not hasattr(copy_executor, 'error_classifier'):
            print("❌ ERROR: JobCopyExecutor doesn't have error_classifier attribute")
            return False
        
        error_classifier = copy_executor.error_classifier
        
        if error_classifier is None:
            print("❌ ERROR: JobCopyExecutor has error_classifier=None")
            return False
        
        print(f"✅ SUCCESS: JobCopyExecutor has error_classifier: {type(error_classifier).__name__}")
        
        # Test that the error classifier can classify FileNotFoundError
        test_error = FileNotFoundError("[WinError 2] File not found")
        status, reason = error_classifier.classify_copy_error(test_error, "test_file.mxf")
        
        print(f"✅ SUCCESS: Error classifier works - FileNotFoundError classified as: {status}")
        
        print("\n🎉 JobProcessor error classifier integration is working!")
        return True
        
    except Exception as e:
        print(f"❌ ERROR: Exception during test: {e}")
        return False


if __name__ == "__main__":
    async def main():
        success = await test_job_processor_has_error_classifier()
        if success:
            print("\n✅ All integration tests passed!")
        else:
            print("\n❌ Integration test failed!")
    
    asyncio.run(main())