"""
Host-specific configuration management utility.

Handles automatic creation and selection of hostname-specific configuration files.
"""

import sys
import socket
import shutil
from pathlib import Path
import logging


def _get_base_dir() -> Path:
    """Return the base directory for settings files.

    When running inside a PyInstaller bundle, settings.env lives next to the
    extracted modules (sys._MEIPASS).  Otherwise we use the current working
    directory (normal development mode).
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(".")


def get_hostname_settings_file() -> str:
    """
    Get the appropriate settings file for this host.

    Logic:
    1. Get current hostname
    2. Check if {hostname}-settings.env exists
    3. If not, create it by copying settings.env
    4. Return the hostname-specific file path

    Returns:
        str: Path to the hostname-specific settings file
    """
    try:
        # Get current hostname (without domain)
        hostname = socket.gethostname().split(".")[0]

        base_dir = _get_base_dir()

        # Define file paths
        base_settings = base_dir / "settings.env"
        host_settings = base_dir / f"{hostname}-settings.env"

        # Check if host-specific settings file exists
        if not host_settings.exists():
            if base_settings.exists():
                # Copy base settings to create host-specific file
                shutil.copy2(base_settings, host_settings)
                logging.info(f"Created host-specific configuration: {host_settings}")

                # Add a comment to the top to indicate it's host-specific
                with open(host_settings, "r", encoding="utf-8") as f:
                    content = f.read()

                host_header = f"""# Host-specific configuration for: {hostname}
# This file was auto-generated from settings.env
# You can now customize settings specifically for this machine
# ==========================================================

"""

                with open(host_settings, "w", encoding="utf-8") as f:
                    f.write(host_header + content)

                logging.info(f"Added hostname header to {host_settings}")
            else:
                logging.warning("Base settings.env not found, falling back to default")
                return "settings.env"
        else:
            logging.debug(
                f"Using existing host-specific configuration: {host_settings}"
            )

        return str(host_settings)

    except Exception as e:
        logging.error(f"Error handling host-specific settings: {e}")
        logging.info("Falling back to default settings.env")
        return "settings.env"


def list_all_settings_files() -> list[str]:
    """
    List all available settings files (base + host-specific).

    Returns:
        list[str]: List of settings file paths
    """
    settings_files = []
    base_dir = _get_base_dir()

    # Check for base settings
    base_settings = base_dir / "settings.env"
    if base_settings.exists():
        settings_files.append(str(base_settings))

    # Check for host-specific settings
    for file_path in base_dir.glob("*-settings.env"):
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
