"""Test output folder template cross-platform path handling."""

import tempfile
from pathlib import Path
import pytest
from app.config import Settings
from app.utils.output_folder_template import OutputFolderTemplateEngine


def test_output_folder_template_cross_platform_paths():
    """Test that folder templates work correctly across different platforms."""

    # Create test settings with cross-platform path separators
    with tempfile.TemporaryDirectory() as temp_dir:
        settings = Settings(
            source_directory=str(Path(temp_dir) / "source"),
            destination_directory=str(Path(temp_dir) / "dest"),
            output_folder_template_enabled=True,
            output_folder_rules="pattern:*Cam*;folder:KAMERA/{date},pattern:*PGM*;folder:PROGRAM/{date}",
            output_folder_default_category="OTHER",
            output_folder_date_format="filename[0:6]",
        )

        engine = OutputFolderTemplateEngine(settings)

        # Test camera file - should go to KAMERA/251022
        camera_file = "251022_1400_Cam_7.mxf"  # Use "Cam" to match "*Cam*" pattern
        camera_output = engine.generate_output_path(camera_file)
        expected_camera = Path(temp_dir) / "dest" / "KAMERA" / "251022" / camera_file

        assert Path(camera_output) == expected_camera

        # Test program file - should go to PROGRAM/251022
        program_file = "251022_1400_PGM_1.mxf"
        program_output = engine.generate_output_path(program_file)
        expected_program = Path(temp_dir) / "dest" / "PROGRAM" / "251022" / program_file

        assert Path(program_output) == expected_program

        # Test other file - should go to OTHER/251022
        other_file = "251022_1400_OTHER.mxf"
        other_output = engine.generate_output_path(other_file)
        expected_other = Path(temp_dir) / "dest" / "OTHER" / "251022" / other_file

        assert Path(other_output) == expected_other


def test_legacy_backslash_rules_converted():
    """Test that legacy backslash rules are converted to forward slashes."""

    with tempfile.TemporaryDirectory() as temp_dir:
        # Use legacy backslash format (should be converted internally)
        settings = Settings(
            source_directory=str(Path(temp_dir) / "source"),
            destination_directory=str(Path(temp_dir) / "dest"),
            output_folder_template_enabled=True,
            output_folder_rules="pattern:*Cam*;folder:KAMERA\\{date}",  # Legacy backslash
            output_folder_default_category="OTHER",
            output_folder_date_format="filename[0:6]",
        )

        engine = OutputFolderTemplateEngine(settings)

        # Should still work correctly despite backslashes in config
        camera_file = "251022_1400_Cam_7.mxf"  # Use "Cam" to match "*Cam*" pattern
        camera_output = engine.generate_output_path(camera_file)
        expected_camera = Path(temp_dir) / "dest" / "KAMERA" / "251022" / camera_file

        assert Path(camera_output) == expected_camera


def test_subfolder_extraction():
    """Test that get_output_subfolder returns correct path."""

    with tempfile.TemporaryDirectory() as temp_dir:
        settings = Settings(
            source_directory=str(Path(temp_dir) / "source"),
            destination_directory=str(Path(temp_dir) / "dest"),
            output_folder_template_enabled=True,
            output_folder_rules="pattern:*Cam*;folder:KAMERA/{date}",
            output_folder_default_category="OTHER",
            output_folder_date_format="filename[0:6]",
        )

        engine = OutputFolderTemplateEngine(settings)

        # Test camera file subfolder
        camera_file = "251022_1400_Cam_7.mxf"  # Use "Cam" to match "*Cam*" pattern
        subfolder = engine.get_output_subfolder(camera_file)

        # Should return path with forward slashes that works on all platforms
        expected_subfolder = "KAMERA/251022"
        assert subfolder == expected_subfolder

        # When used with pathlib, should create correct path for current OS
        full_path = Path(temp_dir) / "dest" / subfolder / camera_file

        # On Windows: dest\KAMERA\251022\filename.mxf
        # On Unix: dest/KAMERA/251022/filename.mxf
        # Both should be valid
        assert full_path.parts[-3] == "KAMERA"
        assert full_path.parts[-2] == "251022"
        assert full_path.parts[-1] == camera_file


if __name__ == "__main__":
    pytest.main([__file__])
