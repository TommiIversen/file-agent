import logging
import logging.handlers
from rich.logging import RichHandler
from rich.console import Console

from .config import Settings


def setup_logging(settings: Settings) -> None:
    log_dir = settings.log_directory
    log_dir.mkdir(parents=True, exist_ok=True)

    # Create Rich console handler for beautiful output
    console = Console(width=120)
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_level=True,
        show_path=True,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        locals_max_length=10,
        locals_max_string=80,
    )
    rich_handler.setLevel(settings.log_level)

    # File handler with detailed format for debugging
    file_format = (
        "%(asctime)s - %(levelname)s - "
        "%(filename)s:%(lineno)d in %(funcName)s() - "
        "%(message)s"
    )

    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=settings.log_file_path,
        when="midnight",
        interval=1,
        backupCount=settings.log_retention_days,
        encoding="utf-8",
    )
    file_handler.setLevel(settings.log_level)
    file_handler.setFormatter(logging.Formatter(file_format))

    # Configure root logger (catches everything)
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)

    # Clear any existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Add only our handlers
    root_logger.addHandler(rich_handler)
    root_logger.addHandler(file_handler)

    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Prevent propagation to avoid duplicate logs
    logging.getLogger().propagate = False

    # Test log with Rich markup
    logging.info(
        f"[bold green]Logging initialized[/] - "
        f"File: [cyan]{settings.log_file_path}[/], "
        f"Level: [yellow]{settings.log_level}[/], "
        f"Retention: [blue]{settings.log_retention_days}[/] days"
    )
