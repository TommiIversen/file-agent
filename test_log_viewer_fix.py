#!/usr/bin/env python3
"""
Test script to verify that the log viewer fix works correctly.
Tests both the old StaticFiles endpoint (which should fail for current log)
and the new API endpoint (which should work for all logs).
"""

import requests
import json
from pathlib import Path

BASE_URL = "http://localhost:8000"

def test_log_files_api():
    """Test the log files listing API"""
    print("🧪 Testing log files API...")
    
    response = requests.get(f"{BASE_URL}/api/log-files")
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Found {len(data.get('log_files', []))} log files")
        
        for log_file in data.get('log_files', []):
            print(f"  - {log_file['filename']} ({log_file['size_mb']} MB)")
            if log_file.get('is_current'):
                print(f"    → Current active log file")
        
        return data.get('log_files', [])
    else:
        print(f"❌ Failed to get log files: {response.status_code}")
        return []

def test_log_content_api(filename):
    """Test the new log content API endpoint"""
    print(f"\n🧪 Testing log content API for: {filename}")
    
    response = requests.get(f"{BASE_URL}/api/log-content/{filename}")
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        if data.get('success'):
            print(f"✅ Successfully loaded {data['filename']}")
            print(f"  - Size: {data['size_mb']} MB ({data['lines']} lines)")
            print(f"  - Is current: {data['is_current']}")
            print(f"  - Content preview: {len(data['content'])} characters")
            
            # Show last few lines for verification
            lines = data['content'].strip().split('\n')
            if lines:
                print(f"  - Last line: {lines[-1][:100]}...")
        else:
            print(f"❌ API returned success=False: {data.get('message')}")
    else:
        print(f"❌ Failed to get log content: {response.status_code}")
        try:
            error_data = response.json()
            print(f"   Error: {error_data.get('detail', 'Unknown error')}")
        except:
            print(f"   Error: {response.text[:200]}")

def test_static_files_endpoint(filename):
    """Test the old StaticFiles endpoint (should fail for current log)"""
    print(f"\n🧪 Testing StaticFiles endpoint for: {filename}")
    
    try:
        response = requests.get(f"{BASE_URL}/logs/{filename}", timeout=10)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            content = response.text
            print(f"✅ Successfully loaded via StaticFiles ({len(content)} characters)")
        else:
            print(f"❌ StaticFiles failed: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ StaticFiles request failed: {e}")

def main():
    print("🔧 Testing Log Viewer Fix")
    print("=" * 50)
    
    # Test log files listing
    log_files = test_log_files_api()
    
    if not log_files:
        print("❌ No log files found, cannot continue testing")
        return
    
    # Find current log file
    current_log = None
    archived_log = None
    
    for log_file in log_files:
        if log_file.get('is_current'):
            current_log = log_file
        else:
            archived_log = log_file
    
    # Test current log file (this used to fail)
    if current_log:
        print(f"\n{'='*50}")
        print(f"Testing CURRENT log file: {current_log['filename']}")
        print(f"{'='*50}")
        
        # Test new API (should work)
        test_log_content_api(current_log['filename'])
        
        # Test old StaticFiles (might fail due to concurrent writes)
        test_static_files_endpoint(current_log['filename'])
    
    # Test archived log file
    if archived_log:
        print(f"\n{'='*50}")
        print(f"Testing ARCHIVED log file: {archived_log['filename']}")
        print(f"{'='*50}")
        
        # Test new API (should work)
        test_log_content_api(archived_log['filename'])
        
        # Test old StaticFiles (should work)
        test_static_files_endpoint(archived_log['filename'])
    
    print(f"\n{'='*50}")
    print("🎉 Test completed!")
    print("The new API endpoint should work for both current and archived logs.")
    print("The StaticFiles endpoint might fail for the current log due to concurrent writes.")

if __name__ == "__main__":
    main()