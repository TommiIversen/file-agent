"""
Output Folder Template Engine for File Transfer Agent.

Provides flexible template-based output folder generation based on input file names.
Supports pattern matching and variable substitution for organized file destinations.

Example usage:
    Input: 200305_1344_Ingest_Cam1.mxf
    Rule: pattern:*Cam*;folder:KAMERA\\{date}
    Output: DESTINATION_DIRECTORY\\KAMERA\\200305\\200305_1344_Ingest_Cam1.mxf
"""

import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from app.config import Settings


@dataclass
class TemplateRule:
    """
    Represents a single template rule for output folder generation.

    Attributes:
        pattern: Glob or regex pattern to match against filename
        folder_template: Template string for output folder structure
        priority: Rule priority (lower number = higher priority)
    """

    pattern: str
    folder_template: str
    priority: int = 100
    is_regex: bool = False

    def matches(self, filename: str) -> bool:
        """Check if this rule matches the given filename."""
        if self.is_regex:
            return bool(re.search(self.pattern, filename, re.IGNORECASE))
        else:
            # Simple wildcard matching
            import fnmatch

            return fnmatch.fnmatch(filename.lower(), self.pattern.lower())


class OutputFolderTemplateEngine:
    """
    Template engine for generating organized output folder structures.

    Features:
    - Pattern-based file categorization
    - Variable extraction from filenames (date, content type, etc.)
    - Flexible template substitution
    - Fallback to default categorization
    """

    def __init__(self, settings: Settings):
        """
        Initialize template engine with configuration.

        Args:
            settings: Application settings containing template configuration
        """
        self.settings = settings
        self.logger = logging.getLogger("app.template_engine")

        # Initialize defaults first
        self.default_category = settings.output_folder_default_category
        self.date_format = settings.output_folder_date_format

        # Parse template rules from settings
        self.rules = self._parse_template_rules()

        self.logger.info(
            f"OutputFolderTemplateEngine initialized with {len(self.rules)} rules"
        )

        if self.rules:
            for rule in self.rules:
                self.logger.debug(
                    f"Rule: pattern='{rule.pattern}' → folder='{rule.folder_template}'"
                )

    def is_enabled(self) -> bool:
        """Check if template engine is enabled."""
        return self.settings.output_folder_template_enabled

    def generate_output_path(self, filename: str, source_path: str = "") -> str:
        """
        Generate complete output path for a given filename.

        Args:
            filename: Input filename to process
            source_path: Optional source path for relative path calculations

        Returns:
            Complete output path including destination directory and template-generated subfolder

        Example:
            filename="200305_1344_Ingest_Cam1.mxf"
            Returns: "C:\\temp_output\\KAMERA\\200305\\200305_1344_Ingest_Cam1.mxf"
        """
        if not self.is_enabled():
            # Template system disabled - use destination directory directly
            return str(Path(self.settings.destination_directory) / filename)

        # Find matching rule
        matching_rule = self._find_matching_rule(filename)

        if matching_rule:
            folder_template = matching_rule.folder_template
            self.logger.debug(f"Using rule for '{filename}': {folder_template}")
        else:
            # Use default category
            folder_template = f"{self.default_category}\\{{date}}"
            self.logger.debug(
                f"Using default category for '{filename}': {folder_template}"
            )

        # Extract variables for substitution
        variables = self._extract_variables(filename)

        # Substitute template variables
        output_subfolder = self._substitute_template(folder_template, variables)

        # Combine with destination directory
        output_path = (
            Path(self.settings.destination_directory) / output_subfolder / filename
        )

        self.logger.info(f"Template mapping: '{filename}' → '{output_path}'")

        return str(output_path)

    def get_output_subfolder(self, filename: str) -> str:
        """
        Get just the subfolder part of the output path (without filename).

        Args:
            filename: Input filename to process

        Returns:
            Subfolder path (e.g., "KAMERA\\200305")
        """
        if not self.is_enabled():
            return ""

        matching_rule = self._find_matching_rule(filename)
        folder_template = (
            matching_rule.folder_template
            if matching_rule
            else f"{self.default_category}\\{{date}}"
        )

        variables = self._extract_variables(filename)
        return self._substitute_template(folder_template, variables)

    def _parse_template_rules(self) -> List[TemplateRule]:
        """
        Parse template rules from settings configuration.

        Supports multiple formats:
        1. Simple format: "pattern:*Cam*;folder:KAMERA\\{date}"
        2. JSON format: [{"pattern": "*Cam*", "folder": "KAMERA\\{date}"}]
        """
        rules = []

        if not self.settings.output_folder_rules:
            return rules

        try:
            # Try parsing as JSON first
            if self.settings.output_folder_rules.strip().startswith("["):
                json_rules = json.loads(self.settings.output_folder_rules)
                for i, rule_data in enumerate(json_rules):
                    rule = TemplateRule(
                        pattern=rule_data.get("pattern", "*"),
                        folder_template=rule_data.get("folder", self.default_category),
                        priority=rule_data.get("priority", i),
                        is_regex=rule_data.get("is_regex", False),
                    )
                    rules.append(rule)
            else:
                # Parse simple format: "pattern:*Cam*;folder:KAMERA\\{date}"
                rule_strings = [
                    r.strip() for r in self.settings.output_folder_rules.split(",")
                ]

                for i, rule_string in enumerate(rule_strings):
                    if not rule_string:
                        continue

                    parts = rule_string.split(";")
                    pattern = ""
                    folder = self.default_category

                    for part in parts:
                        if ":" in part:
                            key, value = part.split(":", 1)
                            if key.strip() == "pattern":
                                pattern = value.strip()
                            elif key.strip() == "folder":
                                folder = value.strip()

                    if pattern:
                        rule = TemplateRule(
                            pattern=pattern, folder_template=folder, priority=i
                        )
                        rules.append(rule)

        except Exception as e:
            self.logger.error(f"Error parsing template rules: {e}")
            self.logger.warning("Template rules parsing failed - using empty rule set")

        # Sort rules by priority
        rules.sort(key=lambda r: r.priority)

        return rules

    def _find_matching_rule(self, filename: str) -> Optional[TemplateRule]:
        """Find the first rule that matches the given filename."""
        for rule in self.rules:
            if rule.matches(filename):
                return rule
        return None

    def _extract_variables(self, filename: str) -> Dict[str, str]:
        """
        Extract variables from filename for template substitution.

        Currently supports:
        - date: Extracted based on date_format setting
        - filename: Full filename
        - name_no_ext: Filename without extension
        """
        variables = {"filename": filename, "name_no_ext": Path(filename).stem}

        # Extract date based on format specification
        if self.date_format.startswith("filename[") and self.date_format.endswith("]"):
            # Extract slice notation: filename[0:6]
            slice_part = self.date_format[9:-1]  # Remove 'filename[' and ']'

            try:
                if ":" in slice_part:
                    start, end = slice_part.split(":")
                    start = int(start) if start else 0
                    end = int(end) if end else len(filename)
                    variables["date"] = filename[start:end]
                else:
                    # Single index
                    index = int(slice_part)
                    variables["date"] = filename[index] if index < len(filename) else ""
            except (ValueError, IndexError) as e:
                self.logger.warning(
                    f"Error extracting date from filename '{filename}': {e}"
                )
                variables["date"] = filename[:6]  # Fallback to first 6 chars
        else:
            # Default: first 6 characters
            variables["date"] = filename[:6]

        return variables

    def _substitute_template(self, template: str, variables: Dict[str, str]) -> str:
        """
        Substitute template variables in the template string.

        Supports {variable_name} format substitution.
        """
        result = template

        for var_name, var_value in variables.items():
            placeholder = f"{{{var_name}}}"
            result = result.replace(placeholder, var_value)

        return result

    def get_template_info(self) -> Dict:
        """
        Get information about the current template configuration.

        Returns:
            Dictionary with template engine status and configuration
        """
        return {
            "enabled": self.is_enabled(),
            "rules_count": len(self.rules),
            "default_category": self.default_category,
            "date_format": self.date_format,
            "rules": [
                {
                    "pattern": rule.pattern,
                    "folder": rule.folder_template,
                    "priority": rule.priority,
                    "is_regex": rule.is_regex,
                }
                for rule in self.rules
            ],
        }


# Utility functions for testing and validation


def test_template_engine():
    """Test the template engine with sample data."""
    from app.config import Settings

    # Create test settings
    settings = Settings(
        source_directory="c:\\temp_input",
        destination_directory="c:\\temp_output",
        output_folder_template_enabled=True,
        output_folder_rules="pattern:*Cam*;folder:KAMERA\\{date},pattern:*PGM*;folder:PROGRAM_CLEAN\\{date},pattern:*CLN*;folder:PROGRAM_CLEAN\\{date}",
        output_folder_default_category="OTHER",
        output_folder_date_format="filename[0:6]",
    )

    engine = OutputFolderTemplateEngine(settings)

    # Test cases
    test_files = [
        "200305_1344_Ingest_Cam1.mxf",
        "200305_1344_Ingest_PGM.mxf",
        "200305_1344_Ingest_CLN.mxf",
        "200305_1344_Something_Else.mxv",
    ]

    print("Template Engine Test Results:")
    print("=" * 50)

    for filename in test_files:
        output_path = engine.generate_output_path(filename)
        subfolder = engine.get_output_subfolder(filename)
        print(f"Input:  {filename}")
        print(f"Output: {output_path}")
        print(f"Folder: {subfolder}")
        print("-" * 30)


if __name__ == "__main__":
    test_template_engine()
