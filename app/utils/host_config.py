"""
Host-specific configuration management utility.

Handles automatic creation and selection of hostname-specific configuration files.

When running as a PyInstaller frozen binary the bundled ``settings.env`` inside
``sys._MEIPASS`` is read-only, so user-editable host-specific files are stored
in ``~/.config/file-agent/`` instead.
"""

import sys
import socket
import shutil
import platform
from pathlib import Path
import logging


# ── Platform-specific default paths ──────────────────────────────────
# When a new host-config is created from the bundled template, Windows
# paths are replaced with sensible macOS defaults (and vice-versa).

_MACOS_REPLACEMENTS = {
    # source / destination  (placeholders the user should edit)
    "SOURCE_DIRECTORY=c:\\temp_input":            "SOURCE_DIRECTORY=/Users/{user}/file-agent-input",
    "DESTINATION_DIRECTORY=\\\\SKumhesten\\testfeta": "DESTINATION_DIRECTORY=/Volumes/share",
    # log path (already handled by run.py env-var, but keep the file consistent)
    "LOG_FILE_PATH=logs/file_agent.log":          "LOG_FILE_PATH=~/Library/Logs/file-agent/file_agent.log",
    # network mount
    "WINDOWS_DRIVE_LETTER=":                      "WINDOWS_DRIVE_LETTER=",
    "MACOS_MOUNT_POINT=/Volumes/sk6505_video":    "MACOS_MOUNT_POINT=/Volumes/sk6505_video",
}

_WINDOWS_REPLACEMENTS = {
    # If someone copies a macOS config to Windows (unlikely, but safe)
    "LOG_FILE_PATH=~/Library/Logs/file-agent/file_agent.log": "LOG_FILE_PATH=logs/file_agent.log",
}


def _apply_platform_defaults(content: str) -> str:
    """Replace platform-specific paths in a newly created config file."""
    import getpass

    replacements = _MACOS_REPLACEMENTS if platform.system() == "Darwin" else _WINDOWS_REPLACEMENTS
    for old, new in replacements.items():
        new = new.replace("{user}", getpass.getuser())
        content = content.replace(old, new)
    return content


def _get_bundled_dir() -> Path:
    """Return the directory that contains the *bundled* (read-only) settings.env.

    For a frozen binary this is ``sys._MEIPASS``; for normal dev mode it is the
    current working directory.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(".")


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
      3. ``<bundled_dir>/settings.env``             (bundled default – read-only)

    If none of the above exist the host-specific file is created by copying the
    bundled default into the writable config directory.

    Returns:
        str: Absolute path to the settings file to use.
    """
    try:
        hostname = socket.gethostname().split(".")[0]

        bundled_dir = _get_bundled_dir()
        config_dir = _get_config_dir()

        host_settings = config_dir / f"{hostname}-settings.env"
        user_base     = config_dir / "settings.env"
        bundled_base  = bundled_dir / "settings.env"

        # 1. Already have a host-specific file → use it
        if host_settings.exists():
            logging.debug(f"Using existing host-specific configuration: {host_settings}")
            return str(host_settings)

        # 2. User placed a settings.env in config dir → use it as-is
        if user_base.exists():
            logging.debug(f"Using user settings override: {user_base}")
            return str(user_base)

        # 3. Bundled default exists → copy to config dir as host-specific
        if bundled_base.exists():
            with open(bundled_base, "r", encoding="utf-8") as f:
                content = f.read()

            # Replace paths with platform-appropriate defaults
            content = _apply_platform_defaults(content)

            host_header = f"""# Host-specific configuration for: {hostname}
# Platform: {platform.system()} ({platform.machine()})
# Auto-generated — edit the values below for this machine
# Location: {host_settings}
# ==========================================================

"""
            with open(host_settings, "w", encoding="utf-8") as f:
                f.write(host_header + content)

            logging.info(f"Created host-specific configuration: {host_settings}")
            return str(host_settings)

        # 4. Nothing found at all
        logging.warning("No settings.env found (bundled or user). Using CWD fallback.")
        return "settings.env"

    except Exception as e:
        logging.error(f"Error handling host-specific settings: {e}")
        logging.info("Falling back to default settings.env")
        return "settings.env"


def list_all_settings_files() -> list[str]:
    """
    List all available settings files (bundled + user config dir).

    Returns:
        list[str]: List of settings file paths
    """
    settings_files = []

    # Check bundled base settings
    bundled_base = _get_bundled_dir() / "settings.env"
    if bundled_base.exists():
        settings_files.append(str(bundled_base))

    # Check user config directory
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
