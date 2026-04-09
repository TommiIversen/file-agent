"""
Directory browsing factories.

DirectoryScannerService.
"""
from app.dependencies.core import (
    _singletons,
    get_settings,
)
from app.domains.directory_browsing.service import DirectoryScannerService


def get_directory_scanner() -> DirectoryScannerService:
    if "directory_scanner" not in _singletons:
        _singletons["directory_scanner"] = DirectoryScannerService(get_settings())
    return _singletons["directory_scanner"]
