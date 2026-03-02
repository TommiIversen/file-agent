"""
Entry point for PyInstaller binary.
Starts the FastAPI app via uvicorn.
"""
import sys
import os
import platform

# Ensure the _internal directory is on the path so 'app' package is found
if getattr(sys, 'frozen', False):
    # Running as PyInstaller bundle
    base_path = sys._MEIPASS
    # Add base path so 'app' is importable as a package
    if base_path not in sys.path:
        sys.path.insert(0, base_path)

    # Set sane defaults for a frozen macOS binary.
    # The install dir (/usr/local/share/file-agent) is root-owned and
    # read-only for the service user, so logs must go somewhere writable.
    if platform.system() == "Darwin":
        log_dir = os.path.expanduser("~/Library/Logs/file-agent")
    else:
        log_dir = os.path.expanduser("~/file-agent-logs")

    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "file_agent.log")
    # Pydantic-settings reads env vars (uppercase) with higher priority
    # than the .env file, so this overrides the bundled default.
    os.environ.setdefault("LOG_FILE_PATH", log_file)

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
