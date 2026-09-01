from __future__ import annotations

import logging

from app.infrastructure.config import Settings
from app.infrastructure.logging_config import configure_logging


def test_configure_logging_writes_rotating_file(tmp_path):
    settings = Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "output", log_level="DEBUG")

    log_path = configure_logging(settings, log_dir=tmp_path / "logs")
    logger = logging.getLogger("app.serialcuts_test")
    logger.info("Проверка логов SerialCuts")

    for handler in logging.getLogger("app").handlers:
        handler.flush()

    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "INFO app.serialcuts_test: Проверка логов SerialCuts" in content


def test_configure_logging_is_idempotent(tmp_path):
    settings = Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "output", log_level="INFO")

    configure_logging(settings, log_dir=tmp_path / "logs")
    configure_logging(settings, log_dir=tmp_path / "logs")

    handlers = [
        handler
        for handler in logging.getLogger("app").handlers
        if getattr(handler, "_serialcuts_configured", False)
    ]
    assert len(handlers) == 2
