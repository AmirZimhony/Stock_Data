"""
Simple logging configuration for containers/Airflow.
Logs to stdout, optionally to file if LOG_DIR is writable.
"""

import logging
import logging.handlers
import os
import sys


def setup_logging():
    """Set up logging: stdout + optional file if LOG_DIR is writable."""
    log_level = os.getenv("LOG_LEVEL", "INFO")
    log_dir = os.getenv("LOG_DIR")

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Add file logging if directory is writable
    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "stock_data_app.log")
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5
            )
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
                )
            )
            logging.getLogger().addHandler(file_handler)
        except (OSError, PermissionError):
            pass  # File logging failed, continue with stdout only

    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)


# Initialize logging
setup_logging()
