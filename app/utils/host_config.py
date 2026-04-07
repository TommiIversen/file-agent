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
import getpass
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


def _generate_default_config(hostname: str) -> str:
    """Generate a clean settings.env with platform-appropriate defaults."""
    user = getpass.getuser()
    is_mac = platform.system() == "Darwin"

    if is_mac:
        source = "/Volumes/NLE-External"
        destination = "/Volumes/share"
        mount_point = "/Volumes/share"
    else:
        source = r"c:\temp_input"
        destination = r"c:\temp_output"
        mount_point = ""

    # log_file_path and database_path are NO LONGER in the env file —
    # they are derived automatically from get_data_dir().

    return f"""# Host-specific configuration for: {hostname}
# Platform: {platform.system()} ({platform.machine()})
# Auto-generated — edit the values below for this machine
#
# Data directory: {get_data_dir()}
#   logs/          — application logs
#   data/          — database
#   config/        — this file
# ==========================================================

# ── Required: Source and destination directories ─────────────────────
SOURCE_DIRECTORY={source}
DESTINATION_DIRECTORY={destination}

# ── Output folder template system ────────────────────────────────────
OUTPUT_FOLDER_TEMPLATE_ENABLED=false
OUTPUT_FOLDER_RULES=
OUTPUT_FOLDER_DEFAULT_CATEGORY=OTHER
OUTPUT_FOLDER_DATE_FORMAT=filename[0:6]

# ── Logging ──────────────────────────────────────────────────────────
LOG_LEVEL=INFO

# ── Network mount (optional) ─────────────────────────────────────────
ENABLE_AUTO_MOUNT=false
NETWORK_SHARE_URL=
WINDOWS_DRIVE_LETTER=
MACOS_MOUNT_POINT={mount_point}

# ── Just In Engine (optional) ────────────────────────────────────────
JUSTIN_API_BASE_URL=http://localhost:8080
# JUSTIN_AUTO_STOP_MINUTES=0
# JUSTIN_AUTO_STOP_WARNING_MINUTES=5

# ── Tally Light (optional) ───────────────────────────────────────────
TALLY_LIGHT_SWITCH_TYPE=ip_power_9255
TALLY_LIGHT_SWITCH_IP=10.65.77.9
"""


def get_hostname_settings_file() -> str:
    """
    Get the appropriate settings file for this host.

    Resolution order:
      1. ``<config_dir>/<hostname>-settings.env`` exists → use it
      2. Generate a fresh ``<hostname>-settings.env`` with platform defaults

    Returns:
        str: Absolute path to the settings file to use.
    """
    try:
        hostname = socket.gethostname().split(".")[0]

        config_dir = get_config_dir()

        host_settings = config_dir / f"{hostname}-settings.env"

        if host_settings.exists():
            logging.debug(f"Using existing host-specific configuration: {host_settings}")
            return str(host_settings)

        # Generate a fresh config with platform-appropriate defaults
        content = _generate_default_config(hostname)
        with open(host_settings, "w", encoding="utf-8") as f:
            f.write(content)

        logging.info(f"Created host-specific configuration: {host_settings}")
        logging.info("Edit this file to set your source and destination directories.")
        return str(host_settings)

    except Exception as e:
        logging.error(f"Error handling host-specific settings: {e}", exc_info=True)
        logging.info("Falling back to default settings.env")
        return "settings.env"


def list_all_settings_files() -> list[str]:
    """List all available settings files in the config directory."""
    settings_files = []
    config_dir = get_config_dir()

    if (config_dir / "settings.env").exists():
        settings_files.append(str(config_dir / "settings.env"))
    for file_path in config_dir.glob("*-settings.env"):
        settings_files.append(str(file_path))

    return settings_files


def get_hostname() -> str:
    """Get the current hostname (without domain)."""
    return socket.gethostname().split(".")[0]


if __name__ == "__main__":
    print(f"Data directory:    {get_data_dir()}")
    print(f"Config directory:  {get_config_dir()}")
    print(f"Logs directory:    {get_logs_dir()}")
    print(f"Database path:     {get_database_path()}")
    print(f"Current hostname:  {get_hostname()}")
    print(f"Settings file:     {get_hostname_settings_file()}")
    print(f"All settings:      {list_all_settings_files()}")
