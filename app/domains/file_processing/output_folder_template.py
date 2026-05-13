"""Output Folder Template Engine for File Transfer Agent."""

import fnmatch
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.config import Settings


@dataclass
class TemplateRule:
    pattern: str
    folder_template: str
    priority: int = 100
    is_regex: bool = False
    ext: str = ""
    _compiled_regex: Optional[re.Pattern[str]] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.is_regex:
            try:
                self._compiled_regex = re.compile(self.pattern, re.IGNORECASE)
            except re.error as e:
                logging.warning(
                    f"Invalid regex pattern '{self.pattern}': {e} — rule will never match"
                )
                self._compiled_regex = None

    def matches(self, filename: str) -> bool:
        pattern_ok = self._matches_pattern(filename)
        ext_ok = self._matches_ext(filename)

        if self.pattern and self.ext:
            return pattern_ok and ext_ok
        if self.ext:
            return ext_ok
        return pattern_ok

    def _matches_pattern(self, filename: str) -> bool:
        if not self.pattern:
            return True
        if self.is_regex:
            if self._compiled_regex is None:
                return False
            return bool(self._compiled_regex.search(filename))
        return fnmatch.fnmatch(filename.lower(), self.pattern.lower())

    def _matches_ext(self, filename: str) -> bool:
        if not self.ext:
            return True
        return Path(filename).suffix.lower() == self.ext.lower()


class OutputFolderTemplateEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = logging.getLogger("app.template_engine")

        # Track which rules string we last parsed, so we re-parse on change
        self._last_rules_str: str = ""
        self._rules: list[TemplateRule] = []

        # Force initial parse
        self._refresh_rules()

        self.logger.info(
            f"OutputFolderTemplateEngine initialized with {len(self._rules)} rules"
        )

        if self._rules:
            for rule in self._rules:
                self.logger.debug(
                    f"Rule: pattern='{rule.pattern}' → folder='{rule.folder_template}'"
                )

    @property
    def default_category(self) -> str:
        return self.settings.output_folder_default_category

    @property
    def date_format(self) -> str:
        return self.settings.output_folder_date_format

    @property
    def time_format(self) -> str:
        return self.settings.output_folder_time_format

    @property
    def rules(self) -> list[TemplateRule]:
        """Return parsed rules, re-parsing if the raw setting has changed."""
        self._refresh_rules()
        return self._rules

    def _refresh_rules(self) -> None:
        """Re-parse rules from settings if the raw string has changed."""
        current = self.settings.output_folder_rules
        if current != self._last_rules_str:
            self._rules = self._parse_template_rules()
            self._last_rules_str = current
            if self._rules:
                self.logger.info(
                    f"OutputFolderTemplateEngine re-parsed rules: {len(self._rules)} rules"
                )

    def is_enabled(self) -> bool:
        return self.settings.output_folder_template_enabled

    def generate_output_path(self, filename: str, source_path: str = "", extra_vars: dict[str, str] | None = None) -> str:
        if not self.is_enabled():
            # Template system disabled - use destination directory directly
            return str(Path(self.settings.destination_directory) / filename)

        # Find matching rule
        matching_rule = self._find_matching_rule(filename)

        if matching_rule:
            folder_template = matching_rule.folder_template
            self.logger.debug(f"Using rule for '{filename}': {folder_template}")
        else:
            # Use default category with forward slash for cross-platform compatibility
            folder_template = f"{self.default_category}/{{date}}"
            self.logger.debug(
                f"Using default category for '{filename}': {folder_template}"
            )

        # Extract variables for substitution
        variables = self._extract_variables(filename)

        # Merge extra variables (e.g. session_time from recording session)
        if extra_vars:
            variables.update(extra_vars)

        # Substitute template variables
        output_subfolder = self._substitute_template(folder_template, variables)

        # Combine with destination directory
        output_path = (
            Path(self.settings.destination_directory) / output_subfolder / filename
        )

        self.logger.info(f"Template mapping: '{filename}' → '{output_path}'")

        return str(output_path)

    def get_output_subfolder(self, filename: str) -> str:
        if not self.is_enabled():
            return ""

        matching_rule = self._find_matching_rule(filename)
        folder_template = (
            matching_rule.folder_template
            if matching_rule
            else f"{self.default_category}/{{date}}"
        )

        variables = self._extract_variables(filename)
        return self._substitute_template(folder_template, variables)

    def _parse_template_rules(self) -> list[TemplateRule]:
        rules: list[TemplateRule] = []

        if not self.settings.output_folder_rules:
            return rules

        try:
            # Try parsing as JSON first
            if self.settings.output_folder_rules.strip().startswith("["):
                json_rules = json.loads(self.settings.output_folder_rules)
                for i, rule_data in enumerate(json_rules):
                    rule = TemplateRule(
                        pattern=rule_data.get("pattern", ""),
                        folder_template=rule_data.get("folder", self.default_category),
                        priority=rule_data.get("priority", i),
                        is_regex=rule_data.get("is_regex", False),
                        ext=rule_data.get("ext", ""),
                    )
                    rules.append(rule)
            else:
                # Parse simple format: "pattern:*Cam*;folder:KAMERA\\{date}"
                # Rules can be separated by commas and/or newlines.
                # NOTE: Patterns containing commas must use JSON format instead,
                # since commas are used as rule delimiters in simple format.
                rule_strings = [
                    r.strip()
                    for r in re.split(r"[,\n]+", self.settings.output_folder_rules)
                ]

                for i, rule_string in enumerate(rule_strings):
                    if not rule_string:
                        continue

                    parts = rule_string.split(";")
                    pattern = ""
                    folder = self.default_category

                    ext = ""

                    for part in parts:
                        if ":" in part:
                            key, value = part.split(":", 1)
                            if key.strip() == "pattern":
                                pattern = value.strip()
                            elif key.strip() == "folder":
                                folder = value.strip()
                            elif key.strip() == "ext":
                                ext = value.strip()

                    if pattern or ext:
                        rule = TemplateRule(
                            pattern=pattern,
                            folder_template=folder,
                            priority=i,
                            ext=ext,
                        )
                        rules.append(rule)

        except Exception as e:
            self.logger.error(f"Error parsing template rules: {e}")
            self.logger.warning("Template rules parsing failed - using empty rule set")

        # Sort rules by priority
        rules.sort(key=lambda r: r.priority)

        return rules

    def _find_matching_rule(self, filename: str) -> Optional[TemplateRule]:
        for rule in self.rules:
            if rule.matches(filename):
                return rule
        return None

    def _extract_variables(self, filename: str) -> dict[str, str]:
        variables = {"filename": filename, "name_no_ext": Path(filename).stem}

        # Extract date based on format specification
        variables["date"] = self._extract_slice(filename, self.date_format, fallback_end=6)

        # Extract time based on format specification
        variables["time"] = self._extract_slice(filename, self.time_format, fallback_end=13)

        return variables

    def _extract_slice(self, filename: str, fmt: str, fallback_end: int) -> str:
        """Extract a substring from *filename* using a ``filename[start:end]`` spec."""
        if fmt.startswith("filename[") and fmt.endswith("]"):
            slice_part = fmt[9:-1]  # Remove 'filename[' and ']'

            try:
                if ":" in slice_part:
                    start_s, end_s = slice_part.split(":")
                    start_idx = int(start_s) if start_s else 0
                    end_idx = int(end_s) if end_s else len(filename)
                    return filename[start_idx:end_idx]
                else:
                    index = int(slice_part)
                    return filename[index] if index < len(filename) else ""
            except (ValueError, IndexError) as e:
                self.logger.warning(
                    f"Error extracting slice '{fmt}' from filename '{filename}': {e}"
                )
                return filename[:fallback_end]
        else:
            return filename[:fallback_end]

    def _substitute_template(self, template: str, variables: dict[str, str]) -> str:
        result = template

        for var_name, var_value in variables.items():
            placeholder = f"{{{var_name}}}"
            result = result.replace(placeholder, var_value)

        # Convert any backslash separators to forward slashes for cross-platform compatibility
        # pathlib will handle proper conversion when creating the Path
        result = result.replace("\\", "/")

        return result

    def get_template_info(self) -> dict:
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
                    "ext": rule.ext,
                }
                for rule in self.rules
            ],
        }
