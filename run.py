"""
Entry point for PyInstaller binary.
Starts the FastAPI app via uvicorn.
"""
import sys
import os

# Pre-load encodings that Jinja2 needs at template-parse time.
# In a PyInstaller bundle these live in the PYZ archive; if they are
# imported lazily (on first template render) a zlib decompression race
# can surface as "LookupError: unknown encoding: unicode-escape".
# Importing them eagerly from the intact base_library.zip prevents this.
import encodings.unicode_escape  # noqa: F401
import encodings.raw_unicode_escape  # noqa: F401

# Ensure the _internal directory is on the path so 'app' package is found
if getattr(sys, 'frozen', False):
    # Running as PyInstaller bundle
    base_path = sys._MEIPASS
    # Add base path so 'app' is importable as a package
    if base_path not in sys.path:
        sys.path.insert(0, base_path)

    # All data paths (logs, db, config) are now handled by
    # app.utils.host_config.get_data_dir() — no env var hacks needed.

# Import the app directly so PyInstaller includes it in the bundle
from app.main import app  # noqa: E402

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        app,  # Pass the app object directly, not a string
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
