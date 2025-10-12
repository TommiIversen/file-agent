#!/usr/bin/env python3
"""
Quick Resume Logging Test

Test script der verificerer at alle resume loggers nu virker korrekt
"""

import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.config import Settings
from app.logging_config import setup_logging

def test_resume_loggers():
    """Test alle resume loggers"""
    print("🧪 Testing Resume Logger Configuration")
    print("=" * 50)
    
    # Setup logging
    settings = Settings()
    setup_logging(settings)
    
    # Test alle resume loggers
    loggers_to_test = [
        "app.job_processor",
        "app.utils.resumable_copy_strategies", 
        "app.utils.secure_resume_verification",
        "app.utils.secure_resume_config",
        "app.utils.resume_integration",
        "app.services.copy_strategies",
        "app.services.growing_file_detector"
    ]
    
    print("Testing loggers:")
    for logger_name in loggers_to_test:
        logger = logging.getLogger(logger_name)
        
        # Test med alle log levels
        logger.info(f"✅ INFO LOG TEST: {logger_name}")
        logger.warning(f"⚠️  WARNING LOG TEST: {logger_name}")
        logger.error(f"❌ ERROR LOG TEST: {logger_name}")
        
        print(f"  ✓ {logger_name}")
    
    print("\n🎯 Resume Detection Simulation:")
    
    # Simuler resume detection logging  
    job_logger = logging.getLogger("app.job_processor")
    job_logger.info("RESUME SCENARIO DETECTED: test_file.mxf (2048000/4096000 bytes = 50.0% complete)")
    job_logger.info("Using RESUME-CAPABLE strategy: ResumableGrowingFileCopyStrategy")
    
    # Simuler resume check logging
    resume_logger = logging.getLogger("app.utils.resumable_copy_strategies") 
    resume_logger.info("RESUME CHECK: Destination exists - running quick integrity check: test_file.mxv")
    resume_logger.info("RESUME CHECK: Size comparison - 2,048,000/4,096,000 bytes (50.0%)")
    resume_logger.info("RESUME COPY: Starting verification for test_file.mxf")
    resume_logger.info("RESUME COPY: Finding safe resume position using paranoid verification...")
    resume_logger.info("RESUME COPY: Verification completed in 1.2s - can preserve 2,048,000 bytes (50.0%)")
    resume_logger.info("RESUME COPY: Truncating destination til resume position 2,048,000 bytes")
    resume_logger.info("RESUME COPY: Continuing copy from position 2,048,000, 2,048,000 bytes remaining")
    
    # Simuler success metrics
    job_logger.info("RESUME METRICS: test_file.mxf - preserved 50.0% of data, verification took 1.2s")
    
    print("\n✅ Logging test completed!")
    print("💡 If you see all log messages above, resume logging is working correctly!")

if __name__ == "__main__":
    test_resume_loggers()