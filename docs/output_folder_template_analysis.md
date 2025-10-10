# Output Folder Template System - Analysis & Design

## Current Pattern Analysis

### Input Files & Desired Mapping:
```
200305_1344_Ingest_Cam1.mxf → DESTINATION_DIRECTORY\KAMERA\200305\200305_1344_Ingest_Cam1.mxf
200305_1344_Ingest_PGM.mxf  → DESTINATION_DIRECTORY\PROGRAM_CLEAN\200305\200305_1344_Ingest_PGM.mxf
200305_1344_Ingest_CLN.mxf  → DESTINATION_DIRECTORY\PROGRAM_CLEAN\200305\200305_1344_Ingest_CLN.mxf
```

### Pattern Components:
1. **Date prefix**: First 6 characters (`200305`)
2. **Content-based mapping**: File content determines folder
3. **Hierarchical structure**: `Category\Date\Filename`

## Proposed Template Systems

### Option 1: Simple Rule-Based Mapping
```env
# Output folder template rules
OUTPUT_TEMPLATE_RULES=[
  "pattern:*Cam*;folder:KAMERA\{date}",
  "pattern:*PGM*;folder:PROGRAM_CLEAN\{date}",
  "pattern:*CLN*;folder:PROGRAM_CLEAN\{date}",
  "default:folder:OTHER\{date}"
]
OUTPUT_TEMPLATE_DATE_FORMAT={filename[0:6]}
```

### Option 2: Advanced Pattern Template
```env
# Flexible template with variables and conditions
OUTPUT_FOLDER_TEMPLATE={base}\{category}\{date}
OUTPUT_TEMPLATE_VARIABLES=[
  "base={DESTINATION_DIRECTORY}",
  "date={filename[0:6]}",
  "category={MATCH(filename): 'Cam.*': 'KAMERA', '(PGM|CLN)': 'PROGRAM_CLEAN', 'default': 'OTHER'}"
]
```

### Option 3: JSON-Style Rules (Most Flexible)
```env
OUTPUT_FOLDER_RULES={
  "template": "{base}\\{category}\\{date}",
  "variables": {
    "base": "{DESTINATION_DIRECTORY}",
    "date": "{filename[0:6]}",
    "category": {
      "type": "pattern_match",
      "rules": [
        {"pattern": "*Cam*", "value": "KAMERA"},
        {"pattern": "*PGM*", "value": "PROGRAM_CLEAN"},
        {"pattern": "*CLN*", "value": "PROGRAM_CLEAN"}
      ],
      "default": "OTHER"
    }
  }
}
```

## Implementation Strategy

### 1. Simple Implementation (Recommended Start)
- Use pattern matching with wildcards
- Support basic variable substitution
- Easy to configure and understand

### 2. Medium Complexity
- Support regex patterns
- Multiple variable extraction methods
- Conditional logic

### 3. Advanced Implementation
- Full template engine
- Complex conditional logic
- Multiple file attributes support

## Code Structure Suggestion

```python
class OutputFolderTemplateEngine:
    def __init__(self, settings: Settings):
        self.rules = self._parse_template_rules(settings)
    
    def generate_output_path(self, filename: str, base_dir: str) -> str:
        # Apply template rules to generate output path
        pass
    
    def _parse_template_rules(self, settings):
        # Parse rules from settings
        pass
    
    def _extract_variables(self, filename: str) -> dict:
        # Extract variables like date, content type, etc.
        pass
```

## Recommended Approach

Start with **Option 1** (Simple Rule-Based) because:
- Easy to configure in .env file
- Covers your current needs
- Can be extended later
- Maintainable and debuggable

Example implementation in settings.env:
```env
# Output folder template configuration
OUTPUT_FOLDER_TEMPLATE_ENABLED=true
OUTPUT_FOLDER_RULES=[
  "pattern:*Cam*;folder:KAMERA\\{date}",
  "pattern:*PGM*;folder:PROGRAM_CLEAN\\{date}",
  "pattern:*CLN*;folder:PROGRAM_CLEAN\\{date}"
]
OUTPUT_FOLDER_DEFAULT=OTHER\\{date}
OUTPUT_FOLDER_DATE_EXTRACT=filename[0:6]
```