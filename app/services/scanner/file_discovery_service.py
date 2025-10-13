# This class is responsible solely for discovering files in the source directory, adhering to SRP.
import asyncio
import logging
import os
from typing import Set
from pathlib import Path
import aiofiles.os

from .domain_objects import FilePath, ScanConfiguration


class FileDiscoveryService:
    """
    Focused service responsible only for discovering MXF files in the source directory.

    Single Responsibility: File discovery and filtering
    """

    def __init__(self, config: ScanConfiguration):
        self.config = config

    async def discover_all_files(self) -> Set[FilePath]:
        """
        Find all MXF files in source directory recursively.

        Returns:
            Set of FilePath objects for all discovered files
        """
        discovered_files: Set[FilePath] = set()

        try:
            source_path = Path(self.config.source_directory)

            if not await aiofiles.os.path.exists(source_path):
                logging.debug(f"Source directory does not exist: {source_path}")
                return discovered_files

            if not await aiofiles.os.path.isdir(source_path):
                logging.debug(f"Source path is not a directory: {source_path}")
                return discovered_files

            # Scan recursively for .mxf files
            for root, _, files in os.walk(source_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    abs_file_path = os.path.abspath(file_path)
                    path_obj = FilePath(abs_file_path)

                    if path_obj.is_mxf_file() and not path_obj.should_ignore():
                        discovered_files.add(path_obj)

            logging.debug(f"Discovered {len(discovered_files)} MXF files")

        except Exception as e:
            logging.error(f"Error discovering files: {e}")

        return discovered_files
