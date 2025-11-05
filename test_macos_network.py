#!/usr/bin/env python3
"""
Test script for macOS network connectivity check.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add the project root to the path  
sys.path.append(str(Path(__file__).parent.parent))

from app.domains.network_mount.macos_mount_utils import MacOSNetworkChecker

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

async def test_network_connectivity():
    """Test the network connectivity methods."""
    print("Testing macOS Network Connectivity")
    print("=" * 40)
    
    checker = MacOSNetworkChecker()
    share_url = "smb://svcsk6402@net.dr.dk/nas/videopodcast/SK6402"
    
    print("\n1. Testing network availability (with share URL):")
    try:
        is_available = await checker.is_network_available(share_url)
        print(f"   Network available for share: {is_available}")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n2. Testing network availability (fallback to gateway):")
    try:
        is_available_fallback = await checker.is_network_available()
        print(f"   Network available (gateway check): {is_available_fallback}")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n3. Testing direct share host connectivity:")
    try:
        can_reach = await checker.can_reach_share_host(share_url)
        print(f"   Can reach share host directly: {can_reach}")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n4. Testing with a known unreachable host:")
    bad_url = "smb://nonexistent.example.com/share"
    try:
        can_reach_bad = await checker.can_reach_share_host(bad_url)
        print(f"   Can reach bad host: {can_reach_bad}")
    except Exception as e:
        print(f"   Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_network_connectivity())