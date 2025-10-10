#!/usr/bin/env python3
"""
Resume Logging Test Script

Dette script tester den nye detaljerede resume logging.
Det bruger UNC share til at simulere network failures og
viser alle resume operationer i detaljeret log output.
"""

import sys
import shutil
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def setup_test_environment():
    """Setup test environment med enhanced logging"""
    print("🔧 Setting up enhanced resume logging test...")
    
    # Read current settings to backup
    settings_path = project_root / "settings.env"
    backup_path = project_root / "settings_backup.env"
    
    # Backup current settings
    if settings_path.exists():
        shutil.copy2(settings_path, backup_path)
        print(f"✅ Backed up settings to {backup_path}")
    
    # Create enhanced test settings
    enhanced_settings = """# Enhanced Resume Logging Test Configuration
SOURCE_FOLDER=c:\\Udv\\file-agent\\test_resume_src
DESTINATION_FOLDER=\\\\localhost\\Flip_in_share\\resume_test

# Basic settings
POLLING_INTERVAL_SECONDS=3
FILE_STABLE_TIME_SECONDS=2
LOG_LEVEL=INFO

# Enhanced resume settings for maximum logging
RESUME_VERIFICATION_MODE=paranoid
RESUME_MIN_FILE_SIZE_MB=1
RESUME_MIN_VERIFY_BYTES=1024
RESUME_BUFFER_SIZE_BYTES=65536
RESUME_VERIFICATION_TIMEOUT_SECONDS=120
RESUME_DETAILED_CORRUPTION_LOGGING=true

# Ensure growing files are handled by resume strategy
GROWING_FILE_DETECTION_ENABLED=true
GROWING_FILE_MIN_SIZE_MB=1
GROWING_FILE_STABLE_TIME_SECONDS=2
"""
    
    # Write enhanced settings
    with open(settings_path, 'w') as f:
        f.write(enhanced_settings)
    
    print(f"✅ Created enhanced test settings in {settings_path}")
    
    # Create test source directory
    source_dir = Path("c:/Udv/file-agent/test_resume_src")
    source_dir.mkdir(exist_ok=True)
    
    print(f"✅ Test source directory ready: {source_dir}")
    
    return backup_path

def create_test_file(source_dir: Path, size_mb: int = 5):
    """Create a test file for resume testing"""
    test_file = source_dir / f"resume_test_{size_mb}mb.mxf"
    
    print(f"📝 Creating {size_mb}MB test file...")
    
    # Create file with recognizable pattern
    chunk_size = 1024 * 1024  # 1MB chunks
    pattern = b"TESTDATA" * (chunk_size // 8)  # Fill 1MB
    
    with open(test_file, 'wb') as f:
        for i in range(size_mb):
            f.write(pattern)
            f.flush()
    
    print(f"✅ Created test file: {test_file}")
    return test_file

def print_test_instructions():
    """Print detaljerede test instruktioner"""
    print("\n" + "="*70)
    print("🧪 ENHANCED RESUME LOGGING TEST INSTRUKTIONER")
    print("="*70)
    
    print("""
1. 📂 FORBEREDELSE:
   - UNC share \\\\localhost\\Flip_in_share skal være tilgængelig
   - Test file er blevet created i source directory
   - Enhanced logging settings er aktiveret
   
2. 🚀 START FILE AGENT:
   - Åbn ny PowerShell window
   - Kør: python main.py
   - Se efter "RESUME CHECK", "RESUME COPY", og "RESUME SCENARIO" logs
   
3. 💔 SIMULER NETWORK FAILURE:
   - Under copy operation, kør: net stop server /y
   - Se efter copy failure og resume detection logs
   - Restart: net start server
   
4. 🔄 OBSERVER RESUME OPERATION:
   - File agent skulle detecte partially copied file
   - Se efter detaljerede verification logs:
     * "RESUME SCENARIO DETECTED" med completion percentage
     * "Using RESUME-CAPABLE strategy" confirmation  
     * "RESUME CHECK" verification steps
     * "Finding safe resume position" med preservation metrics
     * "Truncating destination" og continuation logs
   
5. ✅ VERIFICER SUCCESS:
   - Se efter "RESUME METRICS" med preservation percentage
   - Check at destination file er komplet og korrekt
   
6. 📊 LOG NIVEAUER AT KIGGE EFTER:
   - INFO level: Resume detection og progress
   - WARNING level: Corruption detection og fallbacks  
   - ERROR level: Verification failures og retries
""")
    
    print("="*70)
    print("💡 TIP: Brug 'Get-Content -Wait logs\\file-agent.log' for at følge logs real-time")
    print("="*70)

def restore_settings(backup_path: Path):
    """Restore original settings"""
    settings_path = Path("settings.env")
    
    if backup_path.exists():
        shutil.copy2(backup_path, settings_path)
        backup_path.unlink()
        print("✅ Restored original settings from backup")
    else:
        print("⚠️  No backup found - manual settings restore needed")

def main():
    """Main test setup"""
    print("🧪 Enhanced Resume Logging Test Setup")
    print("="*50)
    
    try:
        # Setup test environment
        backup_path = setup_test_environment()
        
        # Create test file
        source_dir = Path("c:/Udv/file-agent/test_resume_src")
        create_test_file(source_dir, size_mb=5)
        
        # Print instructions
        print_test_instructions()
        
        # Wait for user input
        input("\n⏸️  Press Enter når test er færdig for at restore settings...")
        
        # Restore settings
        restore_settings(backup_path)
        
        print("\n✅ Test completed - settings restored!")
        
    except Exception as e:
        print(f"\n❌ Test setup failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())