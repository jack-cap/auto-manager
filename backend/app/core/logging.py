"""Logging configuration for the application."""

import logging
import sys
from typing import Any

from app.core.config import settings


def setup_logging() -> None:
    """Configure application logging.
    
    Sets up structured logging with appropriate levels based on debug mode.
    """
    # Determine log level based on debug setting
    log_level = logging.DEBUG if settings.debug else logging.INFO
    
    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Configure specific loggers
    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.debug else logging.WARNING
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    # Application logger
    app_logger = logging.getLogger("app")
    app_logger.setLevel(log_level)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a specific module.
    
    Args:
        name: The name of the module (typically __name__)
        
    Returns:
        A configured logger instance
        
    Usage:
        logger = get_logger(__name__)
        logger.info("Processing document")
    """
    return logging.getLogger(f"app.{name}")


class LoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that adds context to log messages.
    
    Usage:
        logger = LoggerAdapter(get_logger(__name__), {"user_id": "123"})
        logger.info("User action")  # Logs: "User action - user_id=123"
    """
    
    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        """Process the log message to include extra context."""
        extra = " - ".join(f"{k}={v}" for k, v in self.extra.items())
        return f"{msg} - {extra}" if extra else msg, kwargs
