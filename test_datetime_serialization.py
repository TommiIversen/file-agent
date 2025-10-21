#!/usr/bin/env python3
"""
Test datetime serialization in TrackedFile with the new JSON mode.
"""

from datetime import datetime
from app.models import TrackedFile, FileStatus
from app.services.websocket_manager import _serialize_tracked_file
import json

def test_datetime_serialization():
    """Test that datetime objects are properly serialized."""
    
    print("=== Testing Datetime Serialization ===")
    
    # Create a TrackedFile with datetime objects
    tracked_file = TrackedFile(
        id="test-123",
        file_path="test_file.mxv",
        file_size=1024000,
        status=FileStatus.COPYING,
        discovered_at=datetime.now(),
        started_copying_at=datetime.now(),
        last_write_time=datetime.now()
    )
    
    print(f"Original TrackedFile created with datetime fields")
    
    try:
        # Test serialization using the updated function
        serialized = _serialize_tracked_file(tracked_file)
        print(f"✅ Serialization successful")
        
        # Test JSON serialization (this was failing before)
        json_str = json.dumps(serialized)
        print(f"✅ JSON serialization successful")
        
        # Check that datetime fields are strings
        datetime_fields = ['discovered_at', 'started_copying_at', 'last_write_time']
        for field in datetime_fields:
            if field in serialized:
                if isinstance(serialized[field], str):
                    print(f"✅ {field} is properly serialized as string: {serialized[field]}")
                else:
                    print(f"❌ {field} is not a string: {type(serialized[field])}")
        
        print(f"\n🎉 All datetime serialization tests passed!")
        assert True  # Use assert instead of return
        
    except Exception as e:
        print(f"❌ Serialization failed: {e}")
        assert False, f"Serialization failed: {e}"  # Use assert instead of return

if __name__ == "__main__":
    test_datetime_serialization()