#!/usr/bin/env python3
"""
Test script for the enhanced mock Justin server with manual mode support.
"""

import asyncio
import httpx
import json

MOCK_SERVER_URL = "http://localhost:8080"

async def test_mock_server():
    """Test the enhanced mock server functionality."""
    
    async with httpx.AsyncClient() as client:
        print("🧪 Testing Enhanced Mock Justin Server")
        print("=" * 50)
        
        # Test 1: Get initial status
        print("\n1️⃣ Testing mock status endpoint...")
        try:
            response = await client.get(f"{MOCK_SERVER_URL}/mock/status")
            if response.status_code == 200:
                status = response.json()
                print(f"   ✅ Mock status: {json.dumps(status, indent=2)}")
            else:
                print(f"   ❌ Failed to get status: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test 2: Get active channels
        print("\n2️⃣ Testing active channels...")
        try:
            response = await client.get(f"{MOCK_SERVER_URL}/ingest/activeChannels")
            if response.status_code == 200:
                channels = response.json()
                print(f"   ✅ Active channels: {channels['channel-names']}")
            else:
                print(f"   ❌ Failed to get channels: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test 3: Check initial recording status for KAM_1
        print("\n3️⃣ Testing initial recording status for KAM_1...")
        try:
            response = await client.post(
                f"{MOCK_SERVER_URL}/ingest/requestRecordingStatus",
                json={"channel": "KAM_1"}
            )
            if response.status_code == 200:
                status = response.json()
                print(f"   ✅ KAM_1 initial rec status: {status.get('rec', 'unknown')}")
            else:
                print(f"   ❌ Failed to get status: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Wait a bit to see auto-cycling
        print("\n⏳ Waiting 8 seconds to observe auto-cycling...")
        await asyncio.sleep(8)
        
        # Test 4: Check status again to see if it changed
        print("\n4️⃣ Testing recording status after auto-cycle...")
        try:
            response = await client.post(
                f"{MOCK_SERVER_URL}/ingest/requestRecordingStatus",
                json={"channel": "KAM_1"}
            )
            if response.status_code == 200:
                status = response.json()
                print(f"   ✅ KAM_1 after auto-cycle: {status.get('rec', 'unknown')}")
            else:
                print(f"   ❌ Failed to get status: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test 5: Start KAM_1 (should switch to manual mode)
        print("\n5️⃣ Testing manual start of KAM_1 (should enable manual mode)...")
        try:
            response = await client.post(
                f"{MOCK_SERVER_URL}/ingest/startChannel",
                json={"channel": "KAM_1"}
            )
            if response.status_code == 200:
                result = response.json()
                print(f"   ✅ Start result: {result}")
            else:
                print(f"   ❌ Failed to start channel: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test 6: Check status after manual start
        print("\n6️⃣ Testing status after manual start...")
        try:
            response = await client.post(
                f"{MOCK_SERVER_URL}/ingest/requestRecordingStatus",
                json={"channel": "KAM_1"}
            )
            if response.status_code == 200:
                status = response.json()
                print(f"   ✅ KAM_1 after manual start: {status.get('rec', 'unknown')}")
            else:
                print(f"   ❌ Failed to get status: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test 7: Check mock status (should be in manual mode now)
        print("\n7️⃣ Testing mock status after manual operation...")
        try:
            response = await client.get(f"{MOCK_SERVER_URL}/mock/status")
            if response.status_code == 200:
                status = response.json()
                print(f"   ✅ Mock status: manual_mode={status.get('manual_mode')}, auto_cycler_running={status.get('auto_cycler_running')}")
            else:
                print(f"   ❌ Failed to get status: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test 8: Stop KAM_1
        print("\n8️⃣ Testing manual stop of KAM_1...")
        try:
            response = await client.post(
                f"{MOCK_SERVER_URL}/ingest/stopChannel",
                json={"channel": "KAM_1"}
            )
            if response.status_code == 200:
                result = response.json()
                print(f"   ✅ Stop result: {result}")
            else:
                print(f"   ❌ Failed to stop channel: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test 9: Check final status
        print("\n9️⃣ Testing final status after manual stop...")
        try:
            response = await client.post(
                f"{MOCK_SERVER_URL}/ingest/requestRecordingStatus",
                json={"channel": "KAM_1"}
            )
            if response.status_code == 200:
                status = response.json()
                print(f"   ✅ KAM_1 after manual stop: {status.get('rec', 'unknown')}")
            else:
                print(f"   ❌ Failed to get status: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        print("\n" + "=" * 50)
        print("🏁 Test completed!")
        print("\n💡 Tips:")
        print("   - Use POST /mock/reset-auto-mode to restart auto-cycling")
        print("   - Use GET /mock/status to check current mode")
        print("   - Any start/stop operation switches to manual mode")

if __name__ == "__main__":
    print("Make sure the mock server is running on http://localhost:8080")
    print("Start it with: python scripts/mock_justin_server.py")
    print()
    
    try:
        asyncio.run(test_mock_server())
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")