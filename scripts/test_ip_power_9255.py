"""
Test Script for IP Power 9255 Integration

Quick test to verify the new power switch implementation works correctly.
"""
import asyncio
import logging
from pathlib import Path
import sys

# Add the app directory to Python path so we can import modules
sys.path.append(str(Path(__file__).parent.parent))

from app.config import Settings
from app.domains.tally_light.factory import create_power_switch
from app.domains.tally_light.protocols import PowerSwitchType, PowerSwitchError

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

async def test_ip_power_9255():
    """Test IP Power 9255 switch functionality."""
    print("🔧 Testing IP Power 9255 Integration")
    print("=" * 50)
    
    # Create settings with IP Power 9255 configuration
    settings = Settings(
        tally_light_switch_type="ip_power_9255",
        tally_light_switch_ip="10.65.77.9",
        tally_light_api_timeout_seconds=3.0
    )
    
    print(f"Switch type: {settings.tally_light_switch_type}")
    print(f"Switch IP: {settings.tally_light_switch_ip}")
    print(f"Timeout: {settings.tally_light_api_timeout_seconds}s")
    print()
    
    # Create power switch using factory
    power_switch = create_power_switch(settings)
    
    print(f"✅ Created switch: {power_switch.switch_type.value}")
    print()
    
    try:
        # Test turning ON
        print("🔴 Testing turn ON...")
        result = await power_switch.turn_on()
        print(f"Result: {result}")
        
        await asyncio.sleep(2)
        
        # Test turning OFF
        print("⚫ Testing turn OFF...")
        result = await power_switch.turn_off()
        print(f"Result: {result}")
        
        # Test status check
        print("📊 Testing status check...")
        try:
            status = await power_switch.get_status()
            print(f"Switch reachable: {status}")
        except PowerSwitchError as e:
            print(f"Status check failed: {e}")
        
        print("✅ All tests completed successfully!")
        
    except PowerSwitchError as e:
        print(f"❌ Power switch error: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
    finally:
        # Clean up
        await power_switch.close()
        print("🧹 Switch client closed")

async def test_mock_switch():
    """Test mock switch for comparison."""
    print("\n🤖 Testing Mock Switch")
    print("=" * 30)
    
    # Create settings for mock switch
    settings = Settings(
        tally_light_switch_type="mock",
        tally_light_switch_ip="localhost:8001"
    )
    
    power_switch = create_power_switch(settings)
    print(f"✅ Created mock switch: {power_switch.switch_type.value}")
    
    try:
        # Test mock operations
        await power_switch.turn_on()
        await power_switch.turn_off()
        status = await power_switch.get_status()
        print(f"Mock status: {status}")
        print("✅ Mock tests completed!")
        
    finally:
        await power_switch.close()

if __name__ == "__main__":
    print("🚀 Starting Power Switch Tests")
    print("Note: Make sure your IP Power 9255 is accessible at 10.65.77.9")
    print()
    
    asyncio.run(test_ip_power_9255())
    asyncio.run(test_mock_switch())