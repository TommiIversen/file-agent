"""
Test script for Output Folder Template System.

Demonstrates how the template system organizes files based on naming patterns.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings
from app.utils.output_folder_template import OutputFolderTemplateEngine


def test_file_organization():
    """Test file organization with various input patterns."""

    print("🎬 File Transfer Agent - Output Folder Template Test")
    print("=" * 60)

    # Load settings
    settings = Settings()

    print(f"📁 Source Directory: {settings.source_directory}")
    print(f"📁 Destination Directory: {settings.destination_directory}")
    print(
        f"⚙️  Template System: {'Enabled' if settings.output_folder_template_enabled else 'Disabled'}"
    )
    print()

    if not settings.output_folder_template_enabled:
        print("❌ Template system is disabled in settings")
        return

    # Initialize template engine
    engine = OutputFolderTemplateEngine(settings)

    print(f"📋 Template Rules ({len(engine.rules)} configured):")
    for rule in engine.rules:
        print(f"   Pattern: {rule.pattern:<15} → Folder: {rule.folder_template}")
    print(f"   Default Category: {engine.default_category}")
    print()

    # Test files that match your requirements
    test_files = [
        # Camera files
        "200305_1344_Ingest_Cam1.mxf",
        "200305_1344_Ingest_Cam2.mxf",
        "210515_0900_Record_Camera_A.mxf",
        # Program files
        "200305_1344_Ingest_PGM.mxf",
        "200305_1344_Ingest_CLN.mxf",
        "210515_0900_Program_PGM.mxf",
        # Other files (fallback)
        "200305_1344_Audio_Track.wav",
        "200305_1344_Metadata.xml",
        "random_file.txt",
    ]

    print("📊 File Organization Results:")
    print("-" * 60)

    for filename in test_files:
        output_path = engine.generate_output_path(filename)
        subfolder = engine.get_output_subfolder(filename)

        # Find which rule matched
        rule = engine._find_matching_rule(filename)
        rule_info = f"Rule: {rule.pattern}" if rule else "Default category"

        print(f"📄 Input:  {filename}")
        print(f"📂 Folder: {subfolder}")
        print(f"📍 Output: {output_path}")
        print(f"🔍 {rule_info}")
        print()


def demonstrate_configuration_options():
    """Show different configuration options."""

    print("\n🔧 Configuration Options")
    print("=" * 40)

    print("Option 1 - Simple Rules (Current):")
    print(
        "OUTPUT_FOLDER_RULES=pattern:*Cam*;folder:KAMERA\\{date},pattern:*PGM*;folder:PROGRAM_CLEAN\\{date}"
    )
    print()

    print("Option 2 - JSON Format (Advanced):")
    json_example = """[
  {"pattern": "*Cam*", "folder": "KAMERA\\\\{date}"},
  {"pattern": "*PGM*", "folder": "PROGRAM_CLEAN\\\\{date}"},
  {"pattern": "*CLN*", "folder": "PROGRAM_CLEAN\\\\{date}"}
]"""
    print(f"OUTPUT_FOLDER_RULES={json_example}")
    print()

    print("Variables available in templates:")
    print("  {date}        - Extracted from filename (first 6 chars by default)")
    print("  {filename}    - Full filename")
    print("  {name_no_ext} - Filename without extension")
    print()

    print("Date extraction formats:")
    print("  filename[0:6]   - First 6 characters (default)")
    print("  filename[0:8]   - First 8 characters")
    print("  filename[6:14]  - Characters 6-14")


if __name__ == "__main__":
    test_file_organization()
    demonstrate_configuration_options()
