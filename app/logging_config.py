"""
Centraliseret logging konfiguration for File Transfer Agent

Supporterer:
- Console logging med farver (development)
- File logging med JSON format (production)
- Daglig log rotation (midnat)
- Automatisk oprydning (30 dage retention)
- Konfigureret via settings.env
"""

import logging
import logging.handlers
from logging.config import dictConfig
from pathlib import Path
import json
from datetime import datetime
from typing import Dict, Any

from .config import Settings


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        # Opret base log record
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Tilføj exception info hvis tilgængelig
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Tilføj ekstra felter hvis de eksisterer
        if hasattr(record, 'request_id'):
            log_entry["request_id"] = record.request_id
        if hasattr(record, 'file_path'):
            log_entry["file_path"] = record.file_path
        if hasattr(record, 'operation'):
            log_entry["operation"] = record.operation
            
        return json.dumps(log_entry, ensure_ascii=False)


class ColoredConsoleFormatter(logging.Formatter):
    """Console formatter med farver for bedre læsbarhed"""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green  
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    def format(self, record: logging.LogRecord) -> str:
        # Tilføj farve til log level
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']
        
        # Format: 2025-10-08 14:30:15 - INFO - app.scanner - Fil opdaget: video.mxf
        formatted = (
            f"{datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')} - "
            f"{color}{record.levelname}{reset} - "
            f"{record.name} - "
            f"{record.getMessage()}"
        )
        
        # Tilføj exception info hvis tilgængelig
        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"
            
        return formatted


def setup_logging(settings: Settings) -> None:
    """
    Opsætter komplet logging system baseret på konfiguration
    
    Args:
        settings: App konfiguration med logging indstillinger
    """
    
    # Sørg for at log directory eksisterer
    log_dir = settings.log_directory
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Log rotation handler - roterer dagligt ved midnat
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=settings.log_file_path,
        when='midnight',
        interval=1,
        backupCount=settings.log_retention_days,
        encoding='utf-8'
    )
    
    # Sæt formatter baseret på konfiguration
    if settings.file_log_format.lower() == "json":
        file_handler.setFormatter(JSONFormatter())
    else:
        file_handler.setFormatter(
            logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        )
    
    # Console handler
    console_handler = logging.StreamHandler()
    if settings.console_log_format.lower() == "colored":
        console_handler.setFormatter(ColoredConsoleFormatter())
    else:
        console_handler.setFormatter(
            logging.Formatter(
                '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
            )
        )
    
    # Logging konfiguration dictionary
    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": JSONFormatter,
            },
            "colored_console": {
                "()": ColoredConsoleFormatter,
            },
            "simple": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "colored_console" if settings.console_log_format.lower() == "colored" else "simple",
                "level": settings.log_level,
                "stream": "ext://sys.stdout"
            },
            "file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "formatter": "json" if settings.file_log_format.lower() == "json" else "simple",
                "level": settings.log_level,
                "filename": settings.log_file_path,
                "when": "midnight",
                "interval": 1,
                "backupCount": settings.log_retention_days,
                "encoding": "utf-8"
            }
        },
        "loggers": {
            # FastAPI/Uvicorn loggers
            "uvicorn": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False
            },
            "uvicorn.access": {
                "handlers": ["console"],
                "level": "INFO", 
                "propagate": False
            },
            "fastapi": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False
            },
            # Core app logger (fanger alle app.* loggers via propagation)
            "app": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            # Explicit app submodule loggers for fine-grained control
            "app.scanner": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            "app.copier": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            "app.state": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            # Resume and utils loggers - CRITICAL for resume logging visibility
            "app.utils": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            "app.utils.resumable_copy_strategies": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            "app.utils.secure_resume_verification": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            "app.utils.secure_resume_config": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            "app.utils.resume_integration": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            # Services loggers
            "app.services": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            "app.services.growing_file_detector": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            "app.services.copy_strategies": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            "app.job_processor": {
                "handlers": ["console", "file"], 
                "level": settings.log_level,
                "propagate": False
            },
            "app.copy_executor": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            },
            "app.strategy_factory": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False
            }
        },
        "root": {
            "level": settings.log_level,
            "handlers": ["console", "file"]
        }
    }
    
    # Anvend logging konfiguration
    dictConfig(LOGGING_CONFIG)
    
    # Log at logging systemet er sat op
    logger = logging.getLogger("app")
    logger.info(
        "Logging system initialiseret",
        extra={
            "operation": "logging_setup",
            "log_file": str(settings.log_file_path),
            "log_level": settings.log_level,
            "retention_days": settings.log_retention_days
        }
    )


def get_logger(name: str) -> logging.Logger:
    """
    Hent en logger til specifik komponent
    
    Args:
        name: Logger navn (f.eks. "app.scanner", "app.copier")
        
    Returns:
        Konfigureret logger instance
    """
    return logging.getLogger(name)


# Convenience loggers til forskellige komponenter
def get_app_logger() -> logging.Logger:
    """Hovedapplikation logger"""
    return get_logger("app")


def get_scanner_logger() -> logging.Logger:
    """File scanner logger"""
    return get_logger("app.scanner")


def get_copier_logger() -> logging.Logger:
    """File copier logger"""
    return get_logger("app.copier")


def get_state_logger() -> logging.Logger:
    """State manager logger"""
    return get_logger("app.state")


# Log utility funktioner
def log_file_operation(logger: logging.Logger, operation: str, file_path: str, **kwargs):
    """
    Log en fil operation med standardiseret format
    
    Args:
        logger: Logger instance
        operation: Operation type (f.eks. "discovered", "copying", "completed")
        file_path: Sti til filen
        **kwargs: Ekstra metadata
    """
    extra = {
        "operation": operation,
        "file_path": file_path,
        **kwargs
    }
    
    message = f"{operation.capitalize()}: {Path(file_path).name}"
    if "file_size" in kwargs:
        size_mb = kwargs["file_size"] / (1024 * 1024)
        message += f" ({size_mb:.1f} MB)"
    
    logger.info(message, extra=extra)


def log_error_with_context(logger: logging.Logger, error: Exception, context: Dict[str, Any]):
    """
    Log en error med fuld kontekst
    
    Args:
        logger: Logger instance  
        error: Exception der skal logges
        context: Kontekstuel information
    """
    logger.error(
        f"Error: {str(error)}",
        exc_info=True,
        extra=context
    )
