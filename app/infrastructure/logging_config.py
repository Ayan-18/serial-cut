from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.infrastructure.config import Settings


_HANDLER_MARKER = "_serialcuts_configured"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(settings: Settings, log_dir: Path | None = None) -> Path:
    logs_dir = log_dir or Path("./data/logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "serialcuts.log"
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    for logger_name in ("app", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        _replace_serialcuts_handlers(logger, level, log_path)
        logger.setLevel(level)
        logger.propagate = logger_name == "app"

    logging.getLogger("serialcuts").setLevel(level)
    return log_path


def _replace_serialcuts_handlers(logger: logging.Logger, level: int, log_path: Path) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(_LOG_FORMAT)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)
    setattr(stream_handler, _HANDLER_MARKER, True)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    setattr(file_handler, _HANDLER_MARKER, True)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
