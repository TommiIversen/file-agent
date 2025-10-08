#!/usr/bin/env python3
"""
Test script til at verificere logging systemet
Tester:
- Console logging med farver
- File logging med JSON format
- Log rotation
- Forskellige log levels
"""

import asyncio
from pathlib import Path
import sys

# Tilføj app til Python path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import Settings
from app.logging_config import (
    setup_logging, 
    get_app_logger, 
    get_scanner_logger, 
    get_copier_logger,
    log_file_operation,
    log_error_with_context
)

async def test_logging_system():
    """Test logging systemet"""
    
    print("🧪 Testing File Transfer Agent Logging System")
    print("=" * 50)
    
    # Load settings
    settings = Settings()
    
    # Setup logging
    setup_logging(settings)
    
    # Get loggers
    app_logger = get_app_logger()
    scanner_logger = get_scanner_logger()
    copier_logger = get_copier_logger()
    
    print(f"📁 Log file: {settings.log_file_path}")
    print(f"📅 Retention: {settings.log_retention_days} days")
    print(f"📊 Log level: {settings.log_level}")
    print()
    
    # Test forskellige log levels
    print("🔍 Testing log levels...")
    app_logger.debug("Dette er en DEBUG besked")
    app_logger.info("Dette er en INFO besked")
    app_logger.warning("Dette er en WARNING besked")
    app_logger.error("Dette er en ERROR besked")
    
    # Test structured logging
    print("\n📋 Testing structured logging...")
    log_file_operation(
        scanner_logger, 
        "discovered", 
        "/source/video1.mxf",
        file_size=1073741824,  # 1GB
        last_modified="2025-10-08T14:30:00Z"
    )
    
    log_file_operation(
        copier_logger,
        "copying",
        "/source/video2.mxf", 
        file_size=2147483648,  # 2GB
        progress=45.5,
        destination="/nas/video2.mxf"
    )
    
    log_file_operation(
        copier_logger,
        "completed",
        "/source/video3.mxf",
        file_size=536870912,  # 512MB
        copy_time_seconds=120
    )
    
    # Test error logging
    print("\n⚠️  Testing error logging...")
    try:
        # Simuler en fejl
        raise FileNotFoundError("Destination ikke tilgængelig")
    except Exception as e:
        log_error_with_context(
            copier_logger,
            e,
            {
                "operation": "file_copy",
                "source": "/source/video4.mxf",
                "destination": "/nas/video4.mxf",
                "retry_count": 2
            }
        )
    
    # Test multiple component logging
    print("\n🔄 Testing multiple components...")
    for i in range(5):
        scanner_logger.info(f"Scanning iteration {i+1}")
        await asyncio.sleep(0.1)
        
        if i % 2 == 0:
            copier_logger.info(f"Processing file batch {i+1}")
    
    # Verificer log fil
    log_file = Path(settings.log_file_path)
    if log_file.exists():
        print(f"\n✅ Log file created: {log_file}")
        print(f"📏 File size: {log_file.stat().st_size} bytes")
        
        # Vis de sidste 3 linjer af log filen
        print("\n📄 Last 3 lines from log file:")
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for line in lines[-3:]:
                print(f"   {line.strip()}")
    else:
        print(f"\n❌ Log file not found: {log_file}")
    
    print("\n🎉 Logging test completed!")
    print("💡 Check console for colored output")
    print(f"📁 Check '{settings.log_file_path}' for JSON formatted logs")

if __name__ == "__main__":
    asyncio.run(test_logging_system())