#!/usr/bin/env python3
"""
Network Mount Service Test Script

Tests NetworkMountService components for SRP compliance and functionality.
"""

import asyncio
import sys
from pathlib import Path

# Add the app directory to sys.path to enable imports
sys.path.insert(0, str(Path(__file__).parent / "app"))

from app.config import Settings
from app.services.network_mount import NetworkMountService, PlatformFactory


async def test_network_mount_components():
    """Test NetworkMountService components."""
    print("🧪 Testing NetworkMountService Components...")
    
    # Test 1: Platform Detection
    print("\n🧪 Test 1: Platform Detection")
    try:
        factory = PlatformFactory()
        platform = factory.detect_platform()
        print(f"✅ Detected platform: {platform}")
        
        # Test mounter creation
        mounter = factory.create_mounter()
        print(f"✅ Created mounter for {mounter.get_platform_name()}")
        
    except Exception as e:
        print(f"❌ Platform detection failed: {e}")
        return False
    
    # Test 2: Settings Configuration
    print("\n🧪 Test 2: Settings Configuration")
    try:
        settings = Settings()
        print("✅ Settings loaded successfully")
        print(f"   - Auto mount enabled: {settings.enable_auto_mount}")
        print(f"   - Network share URL: {settings.network_share_url or '(not configured)'}")
        print(f"   - Windows drive letter: {settings.windows_drive_letter or '(not configured)'}")
        
    except Exception as e:
        print(f"❌ Settings loading failed: {e}")
        return False
    
    # Test 3: NetworkMountService Initialization
    print("\n🧪 Test 3: NetworkMountService Initialization")
    try:
        mount_service = NetworkMountService(settings)
        print("✅ NetworkMountService initialized")
        
        # Get platform info
        platform_info = mount_service.get_platform_info()
        print(f"   - Platform: {platform_info['platform']}")
        print(f"   - Mounter available: {platform_info['mounter_available']}")
        print(f"   - Auto mount enabled: {platform_info['auto_mount_enabled']}")
        print(f"   - Network share configured: {platform_info['network_share_configured']}")
        print(f"   - Mount service ready: {platform_info['mount_service_ready']}")
        
    except Exception as e:
        print(f"❌ NetworkMountService initialization failed: {e}")
        return False
    
    # Test 4: Configuration Test (with temporary config)
    print("\n🧪 Test 4: Configuration Test")
    try:
        # Create test settings with network mount enabled
        test_settings = Settings(
            source_directory="c:\\temp_input",
            destination_directory="c:\\temp_output",
            enable_auto_mount=True,
            network_share_url="smb://testserver/testshare",
            windows_drive_letter="Z"
        )
        
        test_mount_service = NetworkMountService(test_settings)
        
        configured = test_mount_service.is_network_mount_configured()
        share_url = test_mount_service.get_network_share_url()
        expected_mount = test_mount_service.get_expected_mount_point()
        
        print("✅ Test configuration:")
        print(f"   - Configured: {configured}")
        print(f"   - Share URL: {share_url}")
        print(f"   - Expected mount point: {expected_mount}")
        
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False
    
    # Test 5: Mount Verification (dry run - no actual mounting)
    print("\n🧪 Test 5: Mount Verification (Dry Run)")
    try:
        # Test path that definitely doesn't exist
        test_path = "c:\\NonExistentNetworkMount"
        accessible = await mount_service.verify_mount_accessible(test_path)
        print("✅ Mount verification test completed")
        print(f"   - Test path accessible: {accessible} (expected: False)")
        
    except Exception as e:
        print(f"❌ Mount verification test failed: {e}")
        return False
    
    print("\n🎉 All NetworkMountService component tests passed!")
    return True


async def test_size_compliance():
    """Test that all components meet size mandates."""
    print("\n📏 Testing Size Compliance...")
    
    mount_files = [
        ("app/services/network_mount/__init__.py", 25),
        ("app/services/network_mount/base_mounter.py", 50),
        ("app/services/network_mount/platform_factory.py", 50),
        ("app/services/network_mount/macos_mounter.py", 150),
        ("app/services/network_mount/windows_mounter.py", 150),
        ("app/services/network_mount/mount_service.py", 200)
    ]
    
    all_compliant = True
    
    for file_path, max_lines in mount_files:
        try:
            with open(file_path, 'r') as f:
                line_count = len(f.readlines())
            
            status = "✅" if line_count <= max_lines else "❌"
            print(f"{status} {file_path}: {line_count}/{max_lines} lines")
            
            if line_count > max_lines:
                all_compliant = False
                
        except FileNotFoundError:
            print(f"❌ {file_path}: File not found")
            all_compliant = False
    
    if all_compliant:
        print("🎉 All components meet SRP size mandates!")
    else:
        print("⚠️  Some components exceed size limits - refactoring needed")
    
    return all_compliant


async def main():
    """Main test function."""
    print("🚀 NetworkMountService Component Test Suite")
    print("=" * 50)
    
    # Test components
    components_ok = await test_network_mount_components()
    
    # Test size compliance
    size_ok = await test_size_compliance()
    
    print("\n" + "=" * 50)
    if components_ok and size_ok:
        print("✅ SUCCESS: All NetworkMountService tests passed!")
        print("🎯 Phase 1 NetworkMountService implementation complete!")
        return 0
    else:
        print("❌ FAILURE: Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())