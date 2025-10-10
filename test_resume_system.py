"""
Secure Resume System Test

Test script til at validere secure resume funktionalitet.
Simulerer network failures og verificerer resume capabilities.
"""

import asyncio
import time
import tempfile
import logging
from pathlib import Path

from app.utils.secure_resume_config import CONSERVATIVE_CONFIG
from app.utils.resumable_copy_strategies import ResumableNormalFileCopyStrategy
from app.utils.secure_resume_verification import SecureVerificationEngine
from app.models import TrackedFile, FileStatus
from app.config import Settings
from app.services.state_manager import StateManager

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def create_test_files(temp_dir: Path):
    """Create test files for resume testing"""
    logger.info("Creating test files...")
    
    # Create source file (10MB)
    source_file = temp_dir / "test_source.mxf"
    with source_file.open('wb') as f:
        # Write 10MB of data with pattern
        for i in range(10 * 1024):  # 10MB in 1KB chunks
            chunk = f"TEST_DATA_CHUNK_{i:06d}_" + "X" * 1000 + "\n"
            f.write(chunk.encode()[:1024])
    
    # Create partial destination file (simulate interrupted copy)
    dest_file = temp_dir / "test_dest.mxf" 
    with source_file.open('rb') as src, dest_file.open('wb') as dst:
        # Copy first 7MB (simulate interrupted at 70%)
        for i in range(7 * 1024):
            chunk = src.read(1024)
            if not chunk:
                break
            dst.write(chunk)
    
    logger.info(f"Source file: {source_file.stat().st_size:,} bytes")
    logger.info(f"Partial dest: {dest_file.stat().st_size:,} bytes")
    
    return source_file, dest_file


async def test_verification_engine(source_file: Path, dest_file: Path):
    """Test verification engine"""
    logger.info("\n=== Testing Verification Engine ===")
    
    engine = SecureVerificationEngine(CONSERVATIVE_CONFIG)
    
    try:
        resume_position, metrics = await engine.find_safe_resume_position(source_file, dest_file)
        
        logger.info(f"Resume position found: {resume_position:,} bytes")
        metrics.log_metrics()
        
        return resume_position, metrics
        
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        return None, None


async def test_resumable_strategy(source_file: Path, dest_file: Path):
    """Test resumable copy strategy"""
    logger.info("\n=== Testing Resumable Strategy ===")
    
    # Setup minimal dependencies
    settings = Settings()
    state_manager = StateManager()
    
    # Create strategy
    strategy = ResumableNormalFileCopyStrategy(
        settings=settings,
        state_manager=state_manager,
        resume_config=CONSERVATIVE_CONFIG
    )
    
    # Create TrackedFile
    tracked_file = TrackedFile(
        file_path=str(source_file),
        status=FileStatus.COPYING,
        size=source_file.stat().st_size,
        last_modified=source_file.stat().st_mtime
    )
    
    # Test resume capability check
    should_resume = await strategy.should_attempt_resume(source_file, dest_file)
    logger.info(f"Should attempt resume: {should_resume}")
    
    if should_resume:
        # Backup original dest for comparison
        dest_backup = dest_file.with_suffix('.backup')
        dest_backup.write_bytes(dest_file.read_bytes())
        
        logger.info("Starting resume copy...")
        start_time = time.time()
        
        success = await strategy.copy_file(str(source_file), str(dest_file), tracked_file)
        
        elapsed = time.time() - start_time
        logger.info(f"Resume copy result: {success} (took {elapsed:.2f}s)")
        
        if success:
            # Verify final result
            source_size = source_file.stat().st_size
            dest_size = dest_file.stat().st_size
            
            logger.info(f"Final sizes - Source: {source_size:,}, Dest: {dest_size:,}")
            
            if source_size == dest_size:
                logger.info("✅ Resume copy SUCCESS - sizes match!")
                
                # Get resume metrics
                metrics = strategy.get_resume_metrics()
                if metrics:
                    logger.info(f"Data preserved: {metrics.preservation_percentage:.1f}%")
                    logger.info(f"Verification time: {metrics.verification_time_seconds:.2f}s")
                
            else:
                logger.error("❌ Resume copy FAILED - size mismatch!")
        
        return success
    else:
        logger.info("Resume not recommended - would do fresh copy")
        return False


async def test_corruption_scenario(temp_dir: Path):
    """Test corruption detection"""
    logger.info("\n=== Testing Corruption Detection ===")
    
    # Create source file
    source_file = temp_dir / "corrupt_test_source.mxf"
    with source_file.open('wb') as f:
        data = b"GOOD_DATA" * 100000  # ~900KB of good data
        f.write(data)
    
    # Create corrupted destination
    dest_file = temp_dir / "corrupt_test_dest.mxf"
    with dest_file.open('wb') as f:
        # First part good
        data = b"GOOD_DATA" * 50000  # ~450KB good
        f.write(data)
        # Then corrupted data
        corrupt_data = b"BAD_DATA!" * 50000  # ~450KB corrupted
        f.write(corrupt_data)
    
    logger.info(f"Source: {source_file.stat().st_size:,} bytes")
    logger.info(f"Corrupted dest: {dest_file.stat().st_size:,} bytes")
    
    # Test verification engine
    engine = SecureVerificationEngine(CONSERVATIVE_CONFIG)
    
    try:
        resume_position, metrics = await engine.find_safe_resume_position(source_file, dest_file)
        
        logger.info(f"Corruption detected at position: {resume_position:,}")
        logger.info(f"Data that can be preserved: {metrics.preservation_percentage:.1f}%")
        
        if metrics.corruption_detected:
            logger.info("✅ Corruption detection SUCCESS!")
        else:
            logger.warning("⚠️  No corruption detected (unexpected)")
            
        return True
        
    except Exception as e:
        logger.error(f"Corruption test failed: {e}")
        return False


async def run_all_tests():
    """Run all resume functionality tests"""
    logger.info("🚀 Starting Secure Resume System Tests")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        logger.info(f"Using temp directory: {temp_path}")
        
        try:
            # Test 1: Basic resume functionality
            source_file, dest_file = await create_test_files(temp_path)
            
            # Test verification engine
            resume_pos, metrics = await test_verification_engine(source_file, dest_file)
            
            if resume_pos is not None:
                # Test resumable strategy
                await test_resumable_strategy(source_file, dest_file)
            
            # Test 2: Corruption detection
            await test_corruption_scenario(temp_path)
            
            logger.info("\n🎉 All tests completed!")
            
        except Exception as e:
            logger.error(f"Test failed: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(run_all_tests())