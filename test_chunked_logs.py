#!/usr/bin/env python3
"""
Test script to verify chunked log reading and download functionality.
"""

import requests
import json
from pathlib import Path

BASE_URL = "http://localhost:8000"

def test_log_chunk_api():
    """Test the chunked log reading API"""
    print("🧪 Testing chunked log reading API...")
    
    # First get list of log files
    response = requests.get(f"{BASE_URL}/api/log-files")
    if response.status_code != 200:
        print(f"❌ Failed to get log files: {response.status_code}")
        return
        
    data = response.json()
    log_files = data.get('log_files', [])
    
    if not log_files:
        print("❌ No log files found")
        return
    
    # Test with the largest file
    largest_file = max(log_files, key=lambda x: x['size_bytes'])
    filename = largest_file['filename']
    
    print(f"Testing with largest file: {filename} ({largest_file['size_mb']} MB)")
    
    # Test basic chunk loading
    params = {
        'offset': 0,
        'limit': 100,
        'direction': 'forward'
    }
    
    response = requests.get(f"{BASE_URL}/api/log-content/{filename}/chunk", params=params)
    print(f"Chunk API Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        if data.get('success'):
            chunk_info = data['chunk_info']
            print(f"✅ Successfully loaded chunk:")
            print(f"  - Lines in chunk: {len(data['lines'])}")
            print(f"  - Total lines in file: {chunk_info['total_lines']}")
            print(f"  - Offset: {chunk_info['offset']}")
            print(f"  - Has more forward: {chunk_info['has_more_forward']}")
            print(f"  - Has more backward: {chunk_info['has_more_backward']}")
            
            # Test loading more forward
            if chunk_info['has_more_forward']:
                print("\n📄 Testing load more forward...")
                next_params = {
                    'offset': chunk_info['next_forward_offset'],
                    'limit': 100,
                    'direction': 'forward'
                }
                
                response2 = requests.get(f"{BASE_URL}/api/log-content/{filename}/chunk", params=next_params)
                if response2.status_code == 200:
                    data2 = response2.json()
                    if data2.get('success'):
                        print(f"✅ Successfully loaded next chunk ({len(data2['lines'])} lines)")
                    else:
                        print(f"❌ Next chunk failed: {data2.get('message')}")
                else:
                    print(f"❌ Next chunk HTTP error: {response2.status_code}")
            
            # Test backward direction from middle
            print("\n📄 Testing backward direction...")
            middle_offset = min(500, chunk_info['total_lines'] // 2)
            backward_params = {
                'offset': middle_offset,
                'limit': 50,
                'direction': 'backward'
            }
            
            response3 = requests.get(f"{BASE_URL}/api/log-content/{filename}/chunk", params=backward_params)
            if response3.status_code == 200:
                data3 = response3.json()
                if data3.get('success'):
                    print(f"✅ Successfully loaded backward chunk ({len(data3['lines'])} lines)")
                else:
                    print(f"❌ Backward chunk failed: {data3.get('message')}")
            else:
                print(f"❌ Backward chunk HTTP error: {response3.status_code}")
                
        else:
            print(f"❌ Chunk API returned success=False: {data.get('message')}")
    else:
        print(f"❌ Chunk API failed: {response.status_code}")
        try:
            error_data = response.json()
            print(f"   Error: {error_data.get('detail', 'Unknown error')}")
        except:
            print(f"   Error: {response.text[:200]}")


def test_log_download_api():
    """Test the log download API"""
    print("\n🧪 Testing log download API...")
    
    # Get list of log files
    response = requests.get(f"{BASE_URL}/api/log-files")
    if response.status_code != 200:
        print(f"❌ Failed to get log files: {response.status_code}")
        return
        
    data = response.json()
    log_files = data.get('log_files', [])
    
    if not log_files:
        print("❌ No log files found")
        return
    
    # Test with smallest file for faster download
    smallest_file = min(log_files, key=lambda x: x['size_bytes'])
    filename = smallest_file['filename']
    
    print(f"Testing download with: {filename} ({smallest_file['size_mb']} MB)")
    
    try:
        response = requests.get(f"{BASE_URL}/api/log-download/{filename}", stream=True)
        print(f"Download API Status: {response.status_code}")
        
        if response.status_code == 200:
            # Check headers
            headers = response.headers
            print(f"✅ Download headers look good:")
            print(f"  - Content-Type: {headers.get('content-type', 'missing')}")
            print(f"  - Content-Disposition: {headers.get('content-disposition', 'missing')}")
            print(f"  - Content-Length: {headers.get('content-length', 'missing')}")
            
            if 'x-warning' in headers:
                print(f"  - Warning: {headers['x-warning']}")
            
            # Read a small amount to test streaming
            content_size = 0
            for chunk in response.iter_content(chunk_size=1024):
                content_size += len(chunk)
                if content_size > 10240:  # Only read first 10KB for testing
                    break
            
            print(f"✅ Successfully streamed {content_size} bytes")
            
        else:
            print(f"❌ Download failed: {response.status_code}")
            try:
                error_data = response.json()
                print(f"   Error: {error_data.get('detail', 'Unknown error')}")
            except:
                print(f"   Error: {response.text[:200]}")
                
    except Exception as e:
        print(f"❌ Download request failed: {e}")


def test_api_parameter_validation():
    """Test API parameter validation"""
    print("\n🧪 Testing API parameter validation...")
    
    # Get a log file
    response = requests.get(f"{BASE_URL}/api/log-files")
    if response.status_code != 200:
        print("❌ Cannot get log files for validation testing")
        return
        
    data = response.json()
    log_files = data.get('log_files', [])
    
    if not log_files:
        print("❌ No log files for validation testing")
        return
    
    filename = log_files[0]['filename']
    
    # Test invalid parameters
    test_cases = [
        ({"limit": 0}, "zero limit"),
        ({"limit": 15000}, "too large limit"),
        ({"offset": -1}, "negative offset"),
        ({"direction": "sideways"}, "invalid direction"),
    ]
    
    for params, description in test_cases:
        response = requests.get(f"{BASE_URL}/api/log-content/{filename}/chunk", params=params)
        if response.status_code == 400:
            print(f"✅ Correctly rejected {description}")
        else:
            print(f"❌ Failed to reject {description} (status: {response.status_code})")


def main():
    print("🔧 Testing Chunked Log Reading and Download Features")
    print("=" * 60)
    
    test_log_chunk_api()
    test_log_download_api()
    test_api_parameter_validation()
    
    print(f"\n{'='*60}")
    print("🎉 Testing completed!")
    print("Features tested:")
    print("- Chunked log reading with pagination")
    print("- Forward and backward chunk loading")
    print("- Log file download with streaming")
    print("- API parameter validation")


if __name__ == "__main__":
    main()