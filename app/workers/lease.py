"""Job-lease heartbeat and cancellation polling, split out of runner.py: this
is the background thread that keeps a claimed job's lease alive while its
stage functions run, plus the cheap poll used to check for a user cancel."""

from __future__ import annotations

import logging
from threading import Event, Thread

from sqlalchemy.orm import sessionmaker

from app.domain.enums import JobStatus
from app.models.entities import Job
from app.workers.queue import heartbeat_job_lease

logger = logging.getLogger(__name__)


def _job_cancel_requested(bind, job_id: int) -> bool:
    factory = sessionmaker(bind=bind, expire_on_commit=False, autoflush=False)
    with factory() as check_session:
        current = check_session.get(Job, job_id)
        return bool(
            current is not None
            and (current.cancel_requested or current.status == JobStatus.CANCEL_REQUESTED.value)
        )


class _LeaseHeartbeat:
    def __init__(self, bind, job_id: int, worker_id: str, interval_seconds: float = 20.0) -> None:
        self._factory = sessionmaker(bind=bind, expire_on_commit=False, autoflush=False)
        self._job_id = job_id
        self._worker_id = worker_id
        self._interval_seconds = interval_seconds
        self._stop = Event()
        self._thread = Thread(target=self._run, name=f"job-lease-{job_id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            with self._factory() as lease_session:
                try:
                    if not heartbeat_job_lease(lease_session, self._job_id, self._worker_id):
                        logger.warning("Job heartbeat lost lease: job_id=%s", self._job_id)
                        return
                except Exception:
                    logger.exception("Job heartbeat failed: job_id=%s", self._job_id)
                    lease_session.rollback()
