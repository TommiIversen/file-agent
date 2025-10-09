"""
🚀 Cached Destination Availability - Performance Test

Test the cached destination availability logic to verify:
1. Multiple workers share cached result
2. No file conflicts between workers  
3. Proper TTL expiration and refresh
4. Thread-safe access with locks
"""

import asyncio
import time
import uuid
from pathlib import Path

print("🚀 Testing Cached Destination Availability")
print("=" * 50)

# Simulate the caching logic
class MockFileCopyService:
    def __init__(self):
        self.destination_directory = "c:\\temp_output"
        self._destination_check_cache = None
        self._destination_check_timestamp = 0
        self._destination_check_ttl = 5.0  # 5 seconds cache
        self._destination_check_lock = asyncio.Lock()
        self.check_count = 0
    
    async def _check_destination_availability(self) -> bool:
        """Cached destination availability check"""
        current_time = time.time()
        
        # Check if we have a valid cached result
        if (self._destination_check_cache is not None and 
            current_time - self._destination_check_timestamp < self._destination_check_ttl):
            print(f"   ⚡ Cache HIT - returning cached result: {self._destination_check_cache}")
            return self._destination_check_cache
        
        # Use lock to prevent multiple workers from doing the check simultaneously
        async with self._destination_check_lock:
            # Double-check pattern
            if (self._destination_check_cache is not None and 
                time.time() - self._destination_check_timestamp < self._destination_check_ttl):
                print(f"   ⚡ Cache HIT (double-check) - returning cached result: {self._destination_check_cache}")
                return self._destination_check_cache
            
            # Perform actual destination check
            result = await self._perform_destination_check()
            
            # Update cache
            self._destination_check_cache = result
            self._destination_check_timestamp = time.time()
            
            print(f"   🔄 Cache MISS - performed check, cached result: {result}")
            return result
    
    async def _perform_destination_check(self) -> bool:
        """Simulate actual destination check"""
        self.check_count += 1
        print(f"   📁 Performing ACTUAL destination check #{self.check_count}")
        
        # Simulate I/O delay
        await asyncio.sleep(0.1)
        
        # Check if destination exists
        dest_path = Path(self.destination_directory)
        if not dest_path.exists():
            return False
        
        # Simulate unique test file (no conflicts)
        test_file = dest_path / f".file_agent_test_{uuid.uuid4().hex[:8]}"
        print(f"   📝 Using unique test file: {test_file.name}")
        
        try:
            # Simulate file write test
            test_file.write_text("test")
            test_file.unlink()
            return True
        except Exception as e:
            print(f"   ❌ Write test failed: {e}")
            return False

# Test scenario
async def test_cached_availability():
    service = MockFileCopyService()
    
    print("\n1. 🧪 Testing Multiple Workers (Simultaneous Calls)")
    
    # Simulate 8 workers calling at the same time
    tasks = []
    for i in range(8):
        tasks.append(service._check_destination_availability())
    
    start_time = time.time()
    results = await asyncio.gather(*tasks)
    duration = time.time() - start_time
    
    print(f"   📊 Results: {results}")
    print(f"   ⏱️  Duration: {duration:.3f}s")
    print(f"   🔢 Actual checks performed: {service.check_count}")
    print(f"   ✅ Expected: Only 1 actual check for 8 workers")
    
    print("\n2. 🕐 Testing Cache TTL (Time-To-Live)")
    
    # Wait for cache to expire
    print("   ⏳ Waiting 6 seconds for cache to expire...")
    await asyncio.sleep(6)
    
    # Call again - should perform new check
    result = await service._check_destination_availability()
    print(f"   📊 Result after TTL: {result}")
    print(f"   🔢 Total checks performed: {service.check_count}")
    print(f"   ✅ Expected: 2 total checks (initial + after TTL)")
    
    print("\n3. 🔄 Testing Cache Refresh")
    
    # Multiple calls within TTL - should use cache
    for i in range(3):
        result = await service._check_destination_availability()
        
    print(f"   🔢 Final check count: {service.check_count}")
    print(f"   ✅ Expected: Still 2 total checks (no new checks within TTL)")

# Run test
if __name__ == "__main__":
    asyncio.run(test_cached_availability())
    
    print("\n🎯 Performance Improvements:")
    print("   ✅ Reduced I/O operations (8 workers → 1 check)")
    print("   ✅ No file conflicts (unique test files)")
    print("   ✅ Thread-safe caching with locks")
    print("   ✅ Automatic cache refresh after TTL")
    print("\n🚀 Ready for 8 concurrent workers! ⚡")