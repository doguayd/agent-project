import logging
import sys
import os
import platform
from logging.handlers import RotatingFileHandler

MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 5

def setup_logger(name: str, log_file: str = "app.log") -> logging.Logger:
    """
    Sets up a rotating logger that outputs to stderr and a local rotating file.
    - RotatingFileHandler: max 5MB per file, keeps 5 backups.
    - encoding='utf-8', errors='replace': prevents encoding crashes.
    """
    if not os.path.isabs(log_file):
        # Go 3 levels up: services/core/logger_service.py -> services/core -> services -> [Root]
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        log_file = os.path.join(base_path, log_file)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Handler: Stderr (MCP Protocol — only WARNING+ to avoid noise)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    # Handler: Rotating File (everything DEBUG+)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
        errors="replace"        # Replace unencodable chars with '?' — never crashes
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def log_startup_banner(logger: logging.Logger):
    """Write a structured startup banner to the log on every boot."""
    sep = "=" * 70
    logger.info(sep)
    logger.info("MASTER MCP SERVER — STARTUP")
    logger.info(sep)
    logger.info(f"OS         : {platform.system()} {platform.release()} ({platform.machine()})")
    logger.info(f"Python     : {platform.python_version()} @ {sys.executable}")
    logger.info(f"CWD        : {os.getcwd()}")
    logger.info(f"Log File   : app.log (RotatingFileHandler, max 5MB × 5 backups)")
    logger.info(sep)
