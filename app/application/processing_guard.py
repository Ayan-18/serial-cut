from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Iterator


_PROCESSING_LOCK = Lock()


class ProcessingBusyError(RuntimeError):
    pass


@contextmanager
def processing_guard() -> Iterator[None]:
    if not _PROCESSING_LOCK.acquire(blocking=False):
        raise ProcessingBusyError(
            "Уже выполняется другая тяжёлая задача. Дождитесь её завершения или остановите через очередь."
        )
    try:
        yield
    finally:
        _PROCESSING_LOCK.release()
