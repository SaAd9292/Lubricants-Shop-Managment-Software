"""Structured application logging.

Logs to both console and a rotating file under <data_root>/logs/lubripos.log.
Use log levels deliberately:
  DEBUG  - developer tracing
  INFO   - normal lifecycle events (login, sale created, backup taken)
  WARNING- recoverable issues (low stock, failed login attempt)
  ERROR  - failures that abort an operation (db error, restore failure)
NEVER log passwords, password hashes, or full payment data.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False
_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    """Configure root logging once. Safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "lubripos.log"

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(_FORMAT)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    _CONFIGURED = True
    logging.getLogger(__name__).info("Logging initialised -> %s", log_file)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
