"""Test output folder template cross-platform path handling."""

import tempfile
from pathlib import Path
import pytest
from app.config import Settings
from app.domains.file_processing.output_folder_template import OutputFolderTemplateEngine


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


def test_time_variable_groups_files_by_timestamp():
    """Test that {time} variable groups files into sub-folders by timestamp."""

    with tempfile.TemporaryDirectory() as temp_dir:
        settings = Settings(
            source_directory=str(Path(temp_dir) / "source"),
            destination_directory=str(Path(temp_dir) / "dest"),
            output_folder_template_enabled=True,
            output_folder_rules="pattern:*KAM*;folder:KAMERA/{date}/{time}",
            output_folder_default_category="OTHER",
            output_folder_date_format="filename[0:6]",
            output_folder_time_format="filename[7:13]",
        )

        engine = OutputFolderTemplateEngine(settings)

        # Two files with same timestamp should land in the same folder
        file_a = "260408_154246_KAM_3.mxf"
        file_b = "260408_154246_KAM_5.mxf"
        # A file with a different timestamp should land in a different folder
        file_c = "260408_162000_KAM_3.mxf"

        output_a = engine.generate_output_path(file_a)
        output_b = engine.generate_output_path(file_b)
        output_c = engine.generate_output_path(file_c)

        expected_a = Path(temp_dir) / "dest" / "KAMERA" / "260408" / "154246" / file_a
        expected_b = Path(temp_dir) / "dest" / "KAMERA" / "260408" / "154246" / file_b
        expected_c = Path(temp_dir) / "dest" / "KAMERA" / "260408" / "162000" / file_c

        assert Path(output_a) == expected_a
        assert Path(output_b) == expected_b
        assert Path(output_c) == expected_c

        # Same timestamp → same parent folder
        assert Path(output_a).parent == Path(output_b).parent
        # Different timestamp → different parent folder
        assert Path(output_a).parent != Path(output_c).parent


def test_time_variable_subfolder_only():
    """Test get_output_subfolder with {time} variable."""

    with tempfile.TemporaryDirectory() as temp_dir:
        settings = Settings(
            source_directory=str(Path(temp_dir) / "source"),
            destination_directory=str(Path(temp_dir) / "dest"),
            output_folder_template_enabled=True,
            output_folder_rules="pattern:*KAM*;folder:KAMERA/{date}/{time}",
            output_folder_default_category="OTHER",
            output_folder_date_format="filename[0:6]",
            output_folder_time_format="filename[7:13]",
        )

        engine = OutputFolderTemplateEngine(settings)
        subfolder = engine.get_output_subfolder("260408_154246_KAM_3.mxf")
        assert subfolder == "KAMERA/260408/154246"


def test_time_variable_not_used_in_rule():
    """When {time} is NOT in the folder template, files behave as before."""

    with tempfile.TemporaryDirectory() as temp_dir:
        settings = Settings(
            source_directory=str(Path(temp_dir) / "source"),
            destination_directory=str(Path(temp_dir) / "dest"),
            output_folder_template_enabled=True,
            output_folder_rules="pattern:*Cam*;folder:KAMERA/{date}",
            output_folder_default_category="OTHER",
            output_folder_date_format="filename[0:6]",
            output_folder_time_format="filename[7:13]",
        )

        engine = OutputFolderTemplateEngine(settings)
        file = "251022_1400_Cam_7.mxf"
        output = engine.generate_output_path(file)
        expected = Path(temp_dir) / "dest" / "KAMERA" / "251022" / file
        assert Path(output) == expected


def test_ext_only_rule_matches_by_extension():
    """Test that ext-only rules match files by extension."""

    with tempfile.TemporaryDirectory() as temp_dir:
        settings = Settings(
            source_directory=str(Path(temp_dir) / "source"),
            destination_directory=str(Path(temp_dir) / "dest"),
            output_folder_template_enabled=True,
            output_folder_rules="ext:.wav;folder:AUDIO/{date}/{time}",
            output_folder_default_category="OTHER",
            output_folder_date_format="filename[0:6]",
            output_folder_time_format="filename[7:13]",
        )

        engine = OutputFolderTemplateEngine(settings)

        # WAV file should match the ext rule
        wav_file = "260408_154246_MIC_1.wav"
        output = engine.generate_output_path(wav_file)
        expected = Path(temp_dir) / "dest" / "AUDIO" / "260408" / "154246" / wav_file
        assert Path(output) == expected

        # MXF file should NOT match — falls to default
        mxf_file = "260408_154246_KAM_3.mxf"
        output_mxf = engine.generate_output_path(mxf_file)
        expected_mxf = Path(temp_dir) / "dest" / "OTHER" / "260408" / mxf_file
        assert Path(output_mxf) == expected_mxf


def test_ext_combined_with_pattern():
    """Test that ext + pattern combined requires BOTH to match."""

    with tempfile.TemporaryDirectory() as temp_dir:
        settings = Settings(
            source_directory=str(Path(temp_dir) / "source"),
            destination_directory=str(Path(temp_dir) / "dest"),
            output_folder_template_enabled=True,
            output_folder_rules="pattern:*PGM*;ext:.wav;folder:AUDIO_PGM/{date}",
            output_folder_default_category="OTHER",
            output_folder_date_format="filename[0:6]",
        )

        engine = OutputFolderTemplateEngine(settings)

        # WAV + PGM → should match
        wav_pgm = "260408_154246_PGM.wav"
        output = engine.generate_output_path(wav_pgm)
        expected = Path(temp_dir) / "dest" / "AUDIO_PGM" / "260408" / wav_pgm
        assert Path(output) == expected

        # MXF + PGM → should NOT match (wrong extension)
        mxf_pgm = "260408_154246_PGM.mxf"
        output_mxf = engine.generate_output_path(mxf_pgm)
        expected_mxf = Path(temp_dir) / "dest" / "OTHER" / "260408" / mxf_pgm
        assert Path(output_mxf) == expected_mxf

        # WAV + KAM → should NOT match (wrong pattern)
        wav_kam = "260408_154246_KAM_3.wav"
        output_kam = engine.generate_output_path(wav_kam)
        expected_kam = Path(temp_dir) / "dest" / "OTHER" / "260408" / wav_kam
        assert Path(output_kam) == expected_kam


def test_ext_rules_mixed_with_pattern_rules():
    """Test multiple rules mixing ext-only and pattern-only."""

    with tempfile.TemporaryDirectory() as temp_dir:
        settings = Settings(
            source_directory=str(Path(temp_dir) / "source"),
            destination_directory=str(Path(temp_dir) / "dest"),
            output_folder_template_enabled=True,
            output_folder_rules=(
                "pattern:*KAM*;folder:KAMERA/{date}\n"
                "ext:.wav;folder:AUDIO/{date}\n"
                "pattern:*PGM*;folder:PROGRAM/{date}"
            ),
            output_folder_default_category="OTHER",
            output_folder_date_format="filename[0:6]",
        )

        engine = OutputFolderTemplateEngine(settings)

        # KAM MXF → KAMERA
        assert Path(engine.generate_output_path("260408_KAM_3.mxf")) == (
            Path(temp_dir) / "dest" / "KAMERA" / "260408" / "260408_KAM_3.mxf"
        )
        # WAV file → AUDIO
        assert Path(engine.generate_output_path("260408_MIC_1.wav")) == (
            Path(temp_dir) / "dest" / "AUDIO" / "260408" / "260408_MIC_1.wav"
        )
        # PGM MXF → PROGRAM
        assert Path(engine.generate_output_path("260408_PGM.mxf")) == (
            Path(temp_dir) / "dest" / "PROGRAM" / "260408" / "260408_PGM.mxf"
        )
        # Unknown → OTHER
        assert Path(engine.generate_output_path("260408_RANDOM.txt")) == (
            Path(temp_dir) / "dest" / "OTHER" / "260408" / "260408_RANDOM.txt"
        )


def test_ext_rule_json_format():
    """Test ext rules in JSON format."""

    with tempfile.TemporaryDirectory() as temp_dir:
        import json

        rules_json = json.dumps([
            {"ext": ".wav", "folder": "AUDIO/{date}"},
            {"pattern": "*KAM*", "folder": "KAMERA/{date}"},
            {"pattern": "*PGM*", "ext": ".wav", "folder": "AUDIO_PGM/{date}"},
        ])

        settings = Settings(
            source_directory=str(Path(temp_dir) / "source"),
            destination_directory=str(Path(temp_dir) / "dest"),
            output_folder_template_enabled=True,
            output_folder_rules=rules_json,
            output_folder_default_category="OTHER",
            output_folder_date_format="filename[0:6]",
        )

        engine = OutputFolderTemplateEngine(settings)

        # WAV → AUDIO (first rule)
        wav_file = "260408_MIC_1.wav"
        output = engine.generate_output_path(wav_file)
        assert Path(output) == Path(temp_dir) / "dest" / "AUDIO" / "260408" / wav_file

        # KAM MXF → KAMERA (second rule)
        mxf_file = "260408_KAM_3.mxf"
        output_mxf = engine.generate_output_path(mxf_file)
        assert Path(output_mxf) == Path(temp_dir) / "dest" / "KAMERA" / "260408" / mxf_file


def test_newline_delimited_rules():
    """Rules separated by newlines should parse identically to comma-separated."""

    with tempfile.TemporaryDirectory() as temp_dir:
        newline_rules = (
            "pattern:*KAM*;folder:KAMERA/{date}/{time}\n"
            "pattern:*PGM*;folder:PROGRAM/{date}\n"
            "pattern:*CLN*;folder:PROGRAM/{date}"
        )
        settings = Settings(
            source_directory=str(Path(temp_dir) / "source"),
            destination_directory=str(Path(temp_dir) / "dest"),
            output_folder_template_enabled=True,
            output_folder_rules=newline_rules,
            output_folder_default_category="OTHER",
            output_folder_date_format="filename[0:6]",
            output_folder_time_format="filename[7:13]",
        )

        engine = OutputFolderTemplateEngine(settings)
        assert len(engine.rules) == 3

        assert engine.get_output_subfolder("260408_154246_KAM_3.mxf") == "KAMERA/260408/154246"
        assert engine.get_output_subfolder("260408_154246_PGM.mxf") == "PROGRAM/260408"
        assert engine.get_output_subfolder("260408_154246_CLN.mxf") == "PROGRAM/260408"
        assert engine.get_output_subfolder("260408_154246_OTHER.mxf") == "OTHER/260408"


def test_mixed_newline_and_comma_rules():
    """Rules can mix commas and newlines as delimiters."""

    with tempfile.TemporaryDirectory() as temp_dir:
        mixed_rules = "pattern:*KAM*;folder:KAMERA/{date},pattern:*PGM*;folder:PROGRAM/{date}\npattern:*CLN*;folder:PROGRAM/{date}"
        settings = Settings(
            source_directory=str(Path(temp_dir) / "source"),
            destination_directory=str(Path(temp_dir) / "dest"),
            output_folder_template_enabled=True,
            output_folder_rules=mixed_rules,
            output_folder_default_category="OTHER",
            output_folder_date_format="filename[0:6]",
            output_folder_time_format="filename[7:13]",
        )

        engine = OutputFolderTemplateEngine(settings)
        assert len(engine.rules) == 3
        assert engine.get_output_subfolder("260408_154246_KAM_3.mxf") == "KAMERA/260408"
        assert engine.get_output_subfolder("260408_154246_CLN.mxf") == "PROGRAM/260408"


if __name__ == "__main__":
    pytest.main([__file__])
