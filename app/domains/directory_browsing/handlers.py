from app.domains.directory_browsing.service import DirectoryScannerService
from app.domains.directory_browsing.models import DirectoryScanResult
from app.domains.directory_browsing.queries import (
    ScanSourceDirectoryQuery,
    ScanDestinationDirectoryQuery,
    ScanCustomDirectoryQuery,
    GetScannerInfoQuery,
)

# En handler for hver query, der bruger den samme scanner-service

class ScanSourceDirectoryHandler:
    def __init__(self, scanner_service: DirectoryScannerService):
        self._scanner = scanner_service

    async def handle(self, query: ScanSourceDirectoryQuery) -> DirectoryScanResult:
        return await self._scanner.scan_source_directory(
            recursive=query.recursive, max_depth=query.max_depth
        )

class ScanDestinationDirectoryHandler:
    def __init__(self, scanner_service: DirectoryScannerService):
        self._scanner = scanner_service

    async def handle(self, query: ScanDestinationDirectoryQuery) -> DirectoryScanResult:
        return await self._scanner.scan_destination_directory(
            recursive=query.recursive, max_depth=query.max_depth
        )

class ScanCustomDirectoryHandler:
    def __init__(self, scanner_service: DirectoryScannerService):
        self._scanner = scanner_service

    async def handle(self, query: ScanCustomDirectoryQuery) -> DirectoryScanResult:
        return await self._scanner.scan_custom_directory(
            path=query.path, recursive=query.recursive, max_depth=query.max_depth
        )

class GetScannerInfoHandler:
    def __init__(self, scanner_service: DirectoryScannerService):
        self._scanner = scanner_service

    async def handle(self, query: GetScannerInfoQuery) -> dict:
        return self._scanner.get_service_info()