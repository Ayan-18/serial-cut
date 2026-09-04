from __future__ import annotations

import time

import app.workers.background as background
from app.infrastructure.config import Settings
from app.workers.background import BackgroundQueue
from app.workers.runner import WorkerRunResult


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _drive(monkeypatch, *, enabled: bool, result: WorkerRunResult):
    sessions: list[_Session] = []

    def session_factory():
        session = _Session()
        sessions.append(session)
        return session

    notified: list[int | None] = []
    monkeypatch.setattr(background, "SessionLocal", session_factory)
    monkeypatch.setattr(background, "recover_interrupted_jobs", lambda session: 0)
    monkeypatch.setattr(
        background, "effective_settings", lambda session, base: Settings(background_queue_enabled=enabled)
    )
    monkeypatch.setattr(background, "run_next_job", lambda session, settings: result)
    monkeypatch.setattr(background, "notify_job_finished", lambda session, settings, job_id: notified.append(job_id))

    queue = BackgroundQueue()
    queue.start()
    time.sleep(1.1)
    queue.stop()
    return notified


def test_background_queue_notifies_after_a_completed_job(monkeypatch):
    notified = _drive(
        monkeypatch, enabled=True, result=WorkerRunResult(ran=True, job_id=42, status="completed", message="ok")
    )
    assert 42 in notified


def test_background_queue_does_not_notify_when_idle(monkeypatch):
    notified = _drive(
        monkeypatch, enabled=True, result=WorkerRunResult(ran=False, job_id=None, status="idle", message="idle")
    )
    assert notified == []


def test_background_queue_stays_idle_while_disabled(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(background, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(background, "recover_interrupted_jobs", lambda session: 0)
    monkeypatch.setattr(background, "effective_settings", lambda session, base: Settings(background_queue_enabled=False))
    monkeypatch.setattr(background, "run_next_job", lambda session, settings: calls.append(1))

    queue = BackgroundQueue()
    queue.start()
    time.sleep(1.1)
    queue.stop()

    assert calls == []
