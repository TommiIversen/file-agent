"""
Test script for enhanced macOS mount validation and cleanup.

This script tests the new robust mount handling that prevents the dangerous
situation where /Volumes/SK6402 becomes a local folder instead of a network mount.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add the project root to the path
sys.path.append(str(Path(__file__).parent.parent))

from app.domains.network_mount.macos_mount_utils import (
    MacOSMountValidator,
    MacOSNetworkChecker,
    MacOSMountCleaner
)

# Configure logging for testing
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

async def test_mount_validation():
    """Test mount validation utilities."""
    print("🧪 Testing macOS Mount Validation Utilities")
    print("=" * 50)
    
    validator = MacOSMountValidator()
    network_checker = MacOSNetworkChecker()
    _ = MacOSMountCleaner(validator)  # Created but not used in basic test
    
    # Test paths to check
    test_paths = [
        "/Volumes/SK6402",
        "/Volumes/SK6402_1", 
        "/Volumes/SK6402_2",
        "/System/Library",  # Known local path for comparison
    ]
    
    print("\n🔍 Testing mount point validation:")
    for path in test_paths:
        try:
            is_real_mount = await validator.is_real_network_mount(path)
            is_local_folder = await validator.is_local_folder_at_mount_point(path)
            mount_info = await validator.get_mount_info(path)
            
            print(f"  {path}:")
            print(f"    Real network mount: {is_real_mount}")
            print(f"    Local folder at mount point: {is_local_folder}")
            if mount_info:
                print(f"    Mount info: {mount_info['filesystem']} from {mount_info['source']}")
            else:
                print("    Mount info: Not mounted")
            print()
        except Exception as e:
            print(f"  {path}: Error - {e}")
    
    print("\n🌐 Testing network connectivity:")
    try:
        network_available = await network_checker.is_network_available()
        print(f"  Network available: {network_available}")
        
        # Test with the actual share URL from settings
        share_url = "smb://svcsk6402@net.dr.dk/nas/videopodcast/SK6402"
        can_reach_host = await network_checker.can_reach_share_host(share_url)
        print(f"  Can reach share host: {can_reach_host}")
    except Exception as e:
        print(f"  Network test error: {e}")
    
    print("\n👻 Testing ghost mount detection:")
    try:
        ghost_mounts = await validator.find_ghost_mounts("/Volumes/SK6402")
        if ghost_mounts:
            print(f"  Found ghost mounts: {ghost_mounts}")
        else:
            print("  No ghost mounts found")
    except Exception as e:
        print(f"  Ghost mount detection error: {e}")
    
    print("\n✅ Mount validation tests completed!")

async def test_enhanced_macos_mounter():
    """Test the enhanced MacOSMounter with configuration."""
    print("\n🏔️  Testing Enhanced MacOSMounter")
    print("=" * 50)
    
    from app.domains.network_mount.macos_mounter import MacOSMounter
    
    # Test with configured mount point
    configured_mount_point = "/Volumes/SK6402"
    mounter = MacOSMounter(mount_point=configured_mount_point)
    
    share_url = "smb://svcsk6402@net.dr.dk/nas/videopodcast/SK6402"
    
    print("\n📍 Testing mount point derivation:")
    mount_point = mounter.get_mount_point_from_url(share_url)
    print(f"  Expected mount point: {mount_point}")
    print(f"  Should be: {configured_mount_point}")
    
    print("\n🔍 Testing mount verification:")
    try:
        is_mounted, is_accessible = await mounter.verify_mount_accessible(mount_point)
        print(f"  Is mounted: {is_mounted}")
        print(f"  Is accessible: {is_accessible}")
    except Exception as e:
        print(f"  Verification error: {e}")
    
    print("\n✅ Enhanced MacOSMounter tests completed!")

async def main():
    """Run all tests."""
    try:
        await test_mount_validation()
        await test_enhanced_macos_mounter()
        print("\n🎉 All tests completed successfully!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())