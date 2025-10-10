# Output Folder Template System

## 📁 Overview

The Output Folder Template System provides flexible, rule-based organization of copied files based on filename patterns. This allows automatic categorization and structured placement of files in destination directories.

## 🎯 Use Case Example

**Input files:**
```
200305_1344_Ingest_Cam1.mxf  → DESTINATION_DIRECTORY\KAMERA\200305\200305_1344_Ingest_Cam1.mxf
200305_1344_Ingest_PGM.mxf   → DESTINATION_DIRECTORY\PROGRAM_CLEAN\200305\200305_1344_Ingest_PGM.mxf
200305_1344_Ingest_CLN.mxf   → DESTINATION_DIRECTORY\PROGRAM_CLEAN\200305\200305_1344_Ingest_CLN.mxf
```

## ⚙️ Configuration

### Enable Template System
```env
OUTPUT_FOLDER_TEMPLATE_ENABLED=true
```

### Simple Rule Format (Recommended)
```env
OUTPUT_FOLDER_RULES=pattern:*Cam*;folder:KAMERA\{date},pattern:*PGM*;folder:PROGRAM_CLEAN\{date},pattern:*CLN*;folder:PROGRAM_CLEAN\{date}
OUTPUT_FOLDER_DEFAULT_CATEGORY=OTHER
OUTPUT_FOLDER_DATE_FORMAT=filename[0:6]
```

### Advanced JSON Format
```env
OUTPUT_FOLDER_RULES=[
  {"pattern": "*Cam*", "folder": "KAMERA\\{date}"},
  {"pattern": "*PGM*", "folder": "PROGRAM_CLEAN\\{date}"},
  {"pattern": "*CLN*", "folder": "PROGRAM_CLEAN\\{date}"}
]
```

## 🔧 Template Variables

### Available Variables
- `{date}` - Extracted from filename based on date format
- `{filename}` - Full filename with extension
- `{name_no_ext}` - Filename without extension

### Date Extraction Formats
- `filename[0:6]` - First 6 characters (default: "200305")
- `filename[0:8]` - First 8 characters ("20030515")
- `filename[6:14]` - Characters 6-14 (custom extraction)

## 📋 Rule Format

### Simple Format
```
pattern:PATTERN;folder:FOLDER_TEMPLATE
```

### Rule Components
- **pattern**: Wildcard pattern to match filenames (`*Cam*`, `*PGM*`, etc.)
- **folder**: Template for output folder structure

### Multiple Rules
Separate multiple rules with commas:
```
pattern:*Cam*;folder:KAMERA\{date},pattern:*PGM*;folder:PROGRAM_CLEAN\{date}
```

## 🎛️ Pattern Matching

### Wildcard Patterns
- `*Cam*` - Matches any filename containing "Cam"
- `*PGM*` - Matches any filename containing "PGM"
- `Record_*` - Matches filenames starting with "Record_"
- `*_CLN.mxf` - Matches filenames ending with "_CLN.mxf"

### Case Insensitive
All pattern matching is case-insensitive.

## 🔄 Integration Points

### JobProcessor Integration
The template engine is automatically integrated into the job processing workflow:

```python
# JobProcessor uses template engine for destination path calculation
dest_path = build_destination_path_with_template(
    source, source_base, dest_base, self.template_engine
)
```

### Fallback Behavior
- If template system is disabled: Uses standard directory structure preservation
- If no rule matches: Uses `OUTPUT_FOLDER_DEFAULT_CATEGORY`
- If template parsing fails: Falls back to standard behavior with warning

## 📊 Example Configurations

### Video Production Setup
```env
OUTPUT_FOLDER_TEMPLATE_ENABLED=true
OUTPUT_FOLDER_RULES=pattern:*Cam*;folder:CAMERAS\{date},pattern:*PGM*;folder:PROGRAM\{date},pattern:*CLN*;folder:PROGRAM\{date},pattern:*Audio*;folder:AUDIO\{date}
OUTPUT_FOLDER_DEFAULT_CATEGORY=MISC
OUTPUT_FOLDER_DATE_FORMAT=filename[0:6]
```

### Archive Organization
```env
OUTPUT_FOLDER_TEMPLATE_ENABLED=true
OUTPUT_FOLDER_RULES=pattern:*Archive*;folder:ARCHIVE\{date},pattern:*Backup*;folder:BACKUP\{date}
OUTPUT_FOLDER_DEFAULT_CATEGORY=UNSORTED
OUTPUT_FOLDER_DATE_FORMAT=filename[0:8]
```

## 🧪 Testing

### Run Template Demo
```bash
python tests\test_output_folder_template_demo.py
```

### Manual Testing
```python
from app.utils.output_folder_template import test_template_engine
test_template_engine()
```

## 🚨 Error Handling

- **Invalid rule format**: Logs warning, continues with valid rules
- **Template parsing errors**: Falls back to default behavior
- **Missing variables**: Uses empty string or default values
- **Path generation errors**: Falls back to standard path preservation

## 💡 Best Practices

1. **Test rules thoroughly** before production deployment
2. **Use descriptive folder names** for easy organization
3. **Keep patterns specific** to avoid unintended matches
4. **Plan folder hierarchy** to match workflow needs
5. **Monitor logs** for rule matching behavior

## 🔍 Debugging

### Enable Debug Logging
```env
LOG_LEVEL=DEBUG
```

### Check Template Engine Status
```python
processor.template_engine.get_template_info()
```

### Verify Rule Matching
Template engine logs show which rules match each file:
```
Rule: pattern='*Cam*' → folder='KAMERA\{date}'
Template mapping: '200305_1344_Ingest_Cam1.mxf' → 'c:\temp_output\KAMERA\200305\200305_1344_Ingest_Cam1.mxf'
```