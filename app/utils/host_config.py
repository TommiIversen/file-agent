"""
Host-specific configuration management utility.

Handles automatic creation and selection of hostname-specific configuration files.

When running as a PyInstaller frozen binary the bundled ``settings.env`` inside
``sys._MEIPASS`` is read-only, so user-editable host-specific files are stored
in ``~/.config/file-agent/`` instead.
"""

import sys
import socket
import platform
import getpass
from pathlib import Path
import logging


def _generate_default_config(hostname: str) -> str:
    """Generate a clean settings.env with platform-appropriate defaults."""
    user = getpass.getuser()
    is_mac = platform.system() == "Darwin"

    if is_mac:
        source = "/Volumes/NLE-External"
        destination = "/Volumes/share"
        log_path = f"/Users/{user}/Library/Logs/file-agent/file_agent.log"
        mount_point = "/Volumes/share"
    else:
        source = r"c:\temp_input"
        destination = r"c:\temp_output"
        log_path = "logs/file_agent.log"
        mount_point = ""

    return f"""# Host-specific configuration for: {hostname}
# Platform: {platform.system()} ({platform.machine()})
# Auto-generated — edit the values below for this machine
# ==========================================================

# ── Required: Source and destination directories ─────────────────────
SOURCE_DIRECTORY={source}
DESTINATION_DIRECTORY={destination}

# ── Output folder template system ────────────────────────────────────
# ENABLED=true  : Organize files into subfolders based on rules
# ENABLED=false : All files go directly to destination
OUTPUT_FOLDER_TEMPLATE_ENABLED=false
OUTPUT_FOLDER_RULES=
OUTPUT_FOLDER_DEFAULT_CATEGORY=OTHER
OUTPUT_FOLDER_DATE_FORMAT=filename[0:6]

# ── Logging ──────────────────────────────────────────────────────────
LOG_LEVEL=INFO
LOG_FILE_PATH={log_path}

# ── Network mount (optional) ─────────────────────────────────────────
ENABLE_AUTO_MOUNT=false
NETWORK_SHARE_URL=
WINDOWS_DRIVE_LETTER=
MACOS_MOUNT_POINT={mount_point}

# ── Just In Engine (optional) ────────────────────────────────────────
JUSTIN_API_BASE_URL=http://localhost:8080

# ── Tally Light (optional) ───────────────────────────────────────────
TALLY_LIGHT_SWITCH_TYPE=ip_power_9255
TALLY_LIGHT_SWITCH_IP=10.65.77.9
"""


def _get_config_dir() -> Path:
    """Return the *writable* directory for host-specific configuration.

    Frozen binary  → ``~/.config/file-agent/``  (created if missing)
    Dev mode       → current working directory (same as project root)
    """
    if getattr(sys, "frozen", False):
        config_dir = Path.home() / ".config" / "file-agent"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir
    return Path(".")


def get_hostname_settings_file() -> str:
    """
    Get the appropriate settings file for this host.

    Resolution order (first match wins):
      1. ``<config_dir>/<hostname>-settings.env``   (user-customised)
      2. ``<config_dir>/settings.env``              (user-placed override)
      3. Generate a fresh config with platform-appropriate defaults.

    Returns:
        str: Absolute path to the settings file to use.
    """
    try:
        hostname = socket.gethostname().split(".")[0]

        config_dir = _get_config_dir()

        host_settings = config_dir / f"{hostname}-settings.env"
        user_base     = config_dir / "settings.env"

        # 1. Already have a host-specific file → use it
        if host_settings.exists():
            logging.debug(f"Using existing host-specific configuration: {host_settings}")
            return str(host_settings)

        # 2. User placed a settings.env in config dir → use it as-is
        if user_base.exists():
            logging.debug(f"Using user settings override: {user_base}")
            return str(user_base)

        # 3. Generate a fresh config with platform-appropriate defaults
        content = _generate_default_config(hostname)
        with open(host_settings, "w", encoding="utf-8") as f:
            f.write(content)

        logging.info(f"Created host-specific configuration: {host_settings}")
        logging.info("Edit this file to set your source and destination directories.")
        return str(host_settings)

    except Exception as e:
        logging.error(f"Error handling host-specific settings: {e}")
        logging.info("Falling back to default settings.env")
        return "settings.env"


def list_all_settings_files() -> list[str]:
    """
    List all available settings files in the config directory.

    Returns:
        list[str]: List of settings file paths
    """
    settings_files = []
    config_dir = _get_config_dir()

    if (config_dir / "settings.env").exists():
        settings_files.append(str(config_dir / "settings.env"))
    for file_path in config_dir.glob("*-settings.env"):
        settings_files.append(str(file_path))

    return settings_files


def get_hostname() -> str:
    """Get the current hostname (without domain)."""
    return socket.gethostname().split(".")[0]


if __name__ == "__main__":
    # Demo/test functionality
    print(f"Current hostname: {get_hostname()}")
    print(f"Settings file to use: {get_hostname_settings_file()}")
    print(f"All settings files: {list_all_settings_files()}")
