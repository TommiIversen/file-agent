"""
Test for duplicate filename bug
===============================

Dette test demonstrerer problemet hvor:
1. En fil bliver processet og completed
2. En ny fil med samme navn bliver oprettet
3. Systemet fejlagtigt opdaterer den eksisterende TrackedFile i stedet for at oprette en ny

Scenario:
- test.mxv → processed → completed → slettet fra source
- test.mxv (ny fil) → systemet opdaterer eksisterende record i stedet for ny
"""

import asyncio
import tempfile
from pathlib import Path
import pytest

from app.services.state_manager import StateManager
from app.services.scanner.file_scanner_service import FileScannerService  
from app.config import Settings
from app.models import FileStatus


class TestDuplicateFilenameBug:
    """Test duplicate filename detection bug"""

    @pytest.fixture
    def temp_directories(self):
        """Create temporary source and destination directories"""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "source"
            dest_dir = Path(temp_dir) / "dest"
            source_dir.mkdir()
            dest_dir.mkdir()
            yield source_dir, dest_dir

    @pytest.fixture
    def settings(self, temp_directories):
        """Create test settings"""
        source_dir, dest_dir = temp_directories
        return Settings(
            source_directory=str(source_dir),
            destination_directory=str(dest_dir),
            file_stable_time_seconds=1,
            polling_interval_seconds=1,
            enable_growing_file_support=True,
            growing_file_min_size_mb=1
        )

    @pytest.fixture
    def state_manager(self):
        """Create StateManager instance"""
        return StateManager()

    @pytest.fixture
    def file_scanner(self, state_manager, settings):
        """Create FileScannerService instance"""
        return FileScannerService(settings, state_manager)

    @pytest.mark.asyncio
    async def test_duplicate_filename_creates_new_tracked_file(
        self, state_manager, file_scanner, temp_directories
    ):
        """
        Test at en ny fil med samme navn som en completed fil
        opretter en ny TrackedFile record i stedet for at genbruge den gamle.
        """
        source_dir, dest_dir = temp_directories
        test_filename = "test_duplicate.mxf"
        test_file_path = source_dir / test_filename

        # === FØRSTE FIL ===
        print(f"\n🎬 Phase 1: Creating first file: {test_filename}")
        
        # Opret første fil
        test_file_path.write_text("first file content")
        print(f"✅ Created first file with size: {test_file_path.stat().st_size}")
        
        # Lad scanner discovere filen
        await file_scanner.orchestrator._execute_scan_iteration()
        
        # Verificer at filen blev opdaget
        all_files = await state_manager.get_all_files()
        assert len(all_files) == 1
        first_file = all_files[0]
        print(f"✅ First file discovered with ID: {first_file.id}")
        print(f"✅ First file status: {first_file.status}")
        print(f"✅ First file size: {first_file.file_size}")
        
        # Simuler at filen bliver completed og slettet
        await state_manager.update_file_status_by_id(first_file.id, FileStatus.COMPLETED)
        test_file_path.unlink()  # Slet source filen
        print("✅ First file marked as completed and source deleted")
        
        # === ANDEN FIL (SAMME NAVN) ===
        print(f"\n🎬 Phase 2: Creating second file with same name: {test_filename}")
        
        # Opret anden fil med samme navn men forskelligt indhold
        test_file_path.write_text("second file content - much longer content to ensure different size")
        print(f"✅ Created second file with size: {test_file_path.stat().st_size}")
        
        # Lad scanner discovere den nye fil
        await file_scanner.orchestrator._execute_scan_iteration()
        
        # === VERIFICERING ===
        print("\n🔍 Phase 3: Verifying behavior")
        
        # Hent alle filer igen
        all_files = await state_manager.get_all_files()
        print(f"📊 Total files in state: {len(all_files)}")
        
        for i, file in enumerate(all_files):
            print(f"  File {i+1}: ID={file.id}, Status={file.status}, Size={file.file_size}, Path={file.file_path}")
        
        # BUG TEST: Hvis bug eksisterer, vil der stadig kun være 1 fil 
        # og den gamle fil vil have fået opdateret size
        if len(all_files) == 1:
            file = all_files[0]
            if file.id == first_file.id:
                print(f"🐛 BUG DETECTED: Same file ID reused ({file.id})")
                print("🐛 Old file was updated instead of creating new file")
                print(f"🐛 Status: {file.status}, Size: {file.file_size}")
                
                # Dette er den bug vi vil fikse - samme ID bliver genbrugt
                pytest.fail(
                    f"BUG: Scanner reused existing completed file (ID: {file.id}) "
                    f"instead of creating new TrackedFile for new file with same name. "
                    f"New size: {file.file_size}, Original size: {first_file.file_size}"
                )
        
        # FORVENTET ADFÆRD: Der skulle være 2 filer - den completed og den nye
        assert len(all_files) == 2, f"Expected 2 files, got {len(all_files)}"
        
        # Find completed og ny fil
        completed_files = [f for f in all_files if f.status == FileStatus.COMPLETED]
        new_files = [f for f in all_files if f.status != FileStatus.COMPLETED]
        
        assert len(completed_files) == 1, f"Expected 1 completed file, got {len(completed_files)}"
        assert len(new_files) == 1, f"Expected 1 new file, got {len(new_files)}"
        
        completed_file = completed_files[0]
        new_file = new_files[0]
        
        # Verificer at det er forskellige filer
        assert completed_file.id != new_file.id, "Completed and new file should have different IDs"
        assert completed_file.file_size != new_file.file_size, "Files should have different sizes"
        
        print("✅ SUCCESS: Two separate TrackedFile records created")
        print(f"  Completed file: ID={completed_file.id}, Size={completed_file.file_size}")
        print(f"  New file: ID={new_file.id}, Size={new_file.file_size}")

    @pytest.mark.asyncio
    async def test_duplicate_filename_with_multiple_iterations(
        self, state_manager, file_scanner, temp_directories
    ):
        """
        Test flere iterationer af samme filename for at sikre
        at historiske completed files bevares korrekt.
        """
        source_dir, dest_dir = temp_directories
        test_filename = "recurring_job.mxf"
        test_file_path = source_dir / test_filename

        created_files = []
        
        # Opret 3 filer med samme navn over tid
        for iteration in range(3):
            print(f"\n🔄 Iteration {iteration + 1}: Creating {test_filename}")
            
            # Opret fil med unikt indhold
            content = f"iteration {iteration + 1} content " * (iteration + 10)
            test_file_path.write_text(content)
            file_size = test_file_path.stat().st_size
            print(f"✅ Created file with size: {file_size}")
            
            # Scanner discoverer
            await file_scanner.orchestrator._execute_scan_iteration()
            
            # Find den nye fil
            all_files = await state_manager.get_all_files()
            new_file = None
            for file in all_files:
                if file.id not in [f.id for f in created_files] and file.file_path == str(test_file_path):
                    new_file = file
                    break
            
            assert new_file is not None, f"New file not found in iteration {iteration + 1}"
            created_files.append(new_file)
            print(f"✅ New file tracked with ID: {new_file.id}")
            
            # Marker som completed og slet (undtagen sidste)
            if iteration < 2:  # Ikke den sidste
                await state_manager.update_file_status_by_id(new_file.id, FileStatus.COMPLETED)
                test_file_path.unlink()
                print(f"✅ File {iteration + 1} completed and source deleted")
                
                # Kort pause for at simulere realistisk timing
                await asyncio.sleep(0.1)
        
        # === FINAL VERIFICATION ===
        print("\n🔍 Final verification")
        all_files = await state_manager.get_all_files()
        print(f"📊 Total files tracked: {len(all_files)}")
        
        # Skulle have 3 separate filer
        assert len(all_files) == 3, f"Expected 3 files, got {len(all_files)}"
        
        # Verificer alle har forskellige ID'er
        file_ids = [f.id for f in all_files]
        assert len(set(file_ids)) == 3, "All files should have unique IDs"
        
        # Verificer status fordeling
        completed_count = len([f for f in all_files if f.status == FileStatus.COMPLETED])
        active_count = len([f for f in all_files if f.status != FileStatus.COMPLETED])
        
        assert completed_count == 2, f"Expected 2 completed files, got {completed_count}"
        assert active_count == 1, f"Expected 1 active file, got {active_count}"
        
        print(f"✅ SUCCESS: All {len(all_files)} files have unique IDs and correct status")
        for file in all_files:
            print(f"  File: ID={file.id}, Status={file.status}, Size={file.file_size}")


# Manual test function
async def manual_test_duplicate_filename_bug():
    """Manual test for duplicate filename bug"""
    print("🧪 Manual Duplicate Filename Bug Test")
    print("=" * 50)
    
    state_manager = StateManager()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        source_dir = Path(temp_dir) / "source"
        source_dir.mkdir()
        
        settings = Settings(
            source_directory=str(source_dir),
            destination_directory=str(Path(temp_dir) / "dest"),
            file_stable_time_seconds=1
        )
        
        file_scanner = FileScannerService(settings, state_manager)
        test_file = source_dir / "duplicate_test.mxv"
        
        # Primera fil
        print("\n📁 Creating first file...")
        test_file.write_text("first content")
        await file_scanner.orchestrator._execute_scan_iteration()
        
        files = await state_manager.get_all_files()
        print(f"✅ First scan: {len(files)} files")
        if files:
            first_file = files[0]
            print(f"   ID: {first_file.id}, Size: {first_file.file_size}")
            
            # Marker som completed
            await state_manager.update_file_status_by_id(first_file.id, FileStatus.COMPLETED)
            test_file.unlink()
            print("✅ First file completed and deleted")
        
        # Segona fil
        print("\n📁 Creating second file with same name...")
        test_file.write_text("second content with different size")
        await file_scanner.orchestrator._execute_scan_iteration()
        
        files = await state_manager.get_all_files()
        print(f"🔍 After second scan: {len(files)} files")
        
        if len(files) == 1:
            print("🐛 BUG: Only one file found - old file was reused!")
            file = files[0]
            print(f"   Same ID reused: {file.id}")
            print(f"   Status: {file.status}, Size: {file.file_size}")
        else:
            print("✅ SUCCESS: Multiple files found")
            for i, file in enumerate(files):
                print(f"   File {i+1}: ID={file.id}, Status={file.status}, Size={file.file_size}")


if __name__ == "__main__":
    asyncio.run(manual_test_duplicate_filename_bug())