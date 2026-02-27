"""
Entry point for PyInstaller binary.
Starts the FastAPI app via uvicorn.
"""
import sys
import os

# Ensure the _internal directory is on the path so 'app' package is found
if getattr(sys, 'frozen', False):
    # Running as PyInstaller bundle
    base_path = sys._MEIPASS
    # Add base path so 'app' is importable as a package
    if base_path not in sys.path:
        sys.path.insert(0, base_path)
    # Set working directory to where the exe lives (for settings.env etc.)
    os.chdir(os.path.dirname(sys.executable))

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
