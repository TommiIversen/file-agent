"""
Ultra-simple logging configuration for File Transfer Agent

Principles:
- ONE logger for entire app
- Console + File output (with nightly rotation)
- Automatic file/class/line information via %(pathname)s, %(funcName)s, %(lineno)s
- Keep X days of logs
"""

import logging
import logging.handlers

from .config import Settings


def setup_logging(settings: Settings) -> None:
    """
    Setup simple logging: console + rotating file with same content
    """
    
    # Ensure log directory exists
    log_dir = settings.log_directory
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Create formatters
    # Console: colored and readable
    console_format = (
        "%(asctime)s - %(levelname)s - "
        "%(pathname)s:%(lineno)d in %(funcName)s() - "
        "%(message)s"
    )
    
    # File: same info but without colors
    file_format = (
        "%(asctime)s - %(levelname)s - "
        "%(pathname)s:%(lineno)d in %(funcName)s() - "
        "%(message)s"
    )
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(settings.log_level)
    console_handler.setFormatter(logging.Formatter(console_format))
    
    # File handler with nightly rotation
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=settings.log_file_path,
        when='midnight',
        interval=1,
        backupCount=settings.log_retention_days,
        encoding='utf-8'
    )
    file_handler.setLevel(settings.log_level)
    file_handler.setFormatter(logging.Formatter(file_format))
    
    # Configure root logger (catches everything)
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    
    # Test log
    logging.info(
        f"Logging initialized - File: {settings.log_file_path}, "
        f"Level: {settings.log_level}, "
        f"Retention: {settings.log_retention_days} days"
    )


# Simple usage - just use logging directly in your code:
#
# import logging
# 
# # In any file, just call:
# logging.info("File discovered", extra={"file_path": "/path/to/file.mxf"})
# logging.error("Copy failed", exc_info=True)
# logging.debug("Debug info")
#
# The logging system automatically shows file/class/line information!