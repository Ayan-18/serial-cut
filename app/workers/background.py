from __future__ import annotations

from threading import Event, Thread
import logging

from app.application.settings import effective_settings
from app.infrastructure.config import get_settings
from app.infrastructure.database import SessionLocal
from app.workers.queue import recover_interrupted_jobs
from app.workers.runner import run_next_job


logger = logging.getLogger(__name__)


class BackgroundQueue:
    def __init__(self) -> None:
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        logger.info("Starting background queue thread")
        self._stop.clear()
        self._thread = Thread(target=self._run, name="serialcuts-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            logger.info("Background queue thread stopped")

    def _run(self) -> None:
        with SessionLocal() as session:
            recovered = recover_interrupted_jobs(session)
            session.commit()
        if recovered:
            logger.info("Recovered interrupted jobs on background startup: count=%s", recovered)
        while not self._stop.wait(0.75):
            with SessionLocal() as session:
                try:
                    settings = effective_settings(session, get_settings())
                    if not settings.background_queue_enabled:
                        logger.debug("Background queue disabled by settings")
                        continue
                    result = run_next_job(session, settings)
                    session.commit()
                    if result.status in {"idle", "paused", "busy"}:
                        logger.debug(
                            "Background queue skipped run: status=%s message=%s",
                            result.status,
                            result.message,
                        )
                        continue
                except Exception:
                    session.rollback()
                    logger.exception("Background queue iteration failed")


background_queue = BackgroundQueue()
