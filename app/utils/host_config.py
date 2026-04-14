"""
Host-specific configuration management utility.

Handles automatic creation and selection of hostname-specific configuration files.

All user data (config, logs, database) lives under a single **data directory**:

  macOS   → ``~/Library/Application Support/FileAgent/``
  Windows → ``%LOCALAPPDATA%/FileAgent/``
  Linux   → ``~/.local/share/file-agent/``
  Dev     → current working directory (project root)

The ``FILE_AGENT_DATA_DIR`` environment variable can override the default.
"""

import sys
import socket
import platform
from pathlib import Path
import logging


# ── Central data directory ───────────────────────────────────────────

def get_data_dir() -> Path:
    """Return the root directory for all FileAgent user data.

    Resolution order:
      1. ``FILE_AGENT_DATA_DIR`` environment variable (explicit override)
      2. Platform-specific default (see module docstring)
      3. Dev mode (not frozen) → current working directory

    The directory is created if it does not yet exist.
    """
    import os

    explicit = os.environ.get("FILE_AGENT_DATA_DIR")
    if explicit:
        d = Path(explicit)
        d.mkdir(parents=True, exist_ok=True)
        return d

    if getattr(sys, "frozen", False):
        system = platform.system()
        if system == "Darwin":
            d = Path.home() / "Library" / "Application Support" / "FileAgent"
        elif system == "Windows":
            local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
            d = Path(local) / "FileAgent"
        else:
            d = Path.home() / ".local" / "share" / "file-agent"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # Dev mode — project root
    return Path(".")


def get_config_dir() -> Path:
    """Return the config sub-directory (``<data_dir>/config/``)."""
    d = get_data_dir() / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_logs_dir() -> Path:
    """Return the logs sub-directory (``<data_dir>/logs/``)."""
    d = get_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_database_path() -> str:
    """Return the default path to the SQLite database file."""
    d = get_data_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / "file-agent.db")


def get_hostname() -> str:
    """Get the current hostname (without domain)."""
    return socket.gethostname().split(".")[0]


if __name__ == "__main__":
    print(f"Data directory:    {get_data_dir()}")
    print(f"Config directory:  {get_config_dir()}")
    print(f"Logs directory:    {get_logs_dir()}")
    print(f"Database path:     {get_database_path()}")
    print(f"Current hostname:  {get_hostname()}")
