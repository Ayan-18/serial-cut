from __future__ import annotations

import app.bot.notifications as notifications
from app.bot.notifications import notify_job_finished
from app.domain.enums import JobKind, JobStatus
from app.infrastructure.config import Settings
from app.models.entities import AppSetting, ClipCandidate, Episode, Job, Season


def _episode(session) -> int:
    season = Season(title="S", root_path="C:/tg-notify")
    session.add(season)
    session.flush()
    episode = Episode(
        season_id=season.id,
        file_path="C:/tg-notify/e01.mkv",
        file_name="e01.mkv",
        fingerprint="fp-tg-notify",
        size_bytes=1,
        modified_ns=1,
    )
    session.add(episode)
    session.flush()
    return episode.id


def _analyze_job(session, episode_id: int) -> Job:
    job = Job(
        episode_id=episode_id,
        kind=JobKind.ANALYZE_EPISODE.value,
        status=JobStatus.COMPLETED.value,
    )
    session.add(job)
    session.flush()
    return job


def test_notify_is_a_noop_without_a_configured_bot(session, monkeypatch):
    episode_id = _episode(session)
    job = _analyze_job(session, episode_id)
    calls: list = []
    monkeypatch.setattr(notifications, "_deliver", lambda *a: calls.append(a) or True)

    notify_job_finished(session, Settings(), job.id)

    assert calls == []
    assert session.get(AppSetting, f"telegram_notified:{job.id}") is None


def test_notify_sends_once_and_records_a_marker(session, monkeypatch):
    episode_id = _episode(session)
    session.add(
        ClipCandidate(
            episode_id=episode_id, start_time=0, end_time=30, title="c", description="d",
            moment_type="другое", score=80, scores_json={}, rationale="r", problems_json=[],
        )
    )
    job = _analyze_job(session, episode_id)
    session.flush()
    sent: list = []
    monkeypatch.setattr(notifications, "_deliver", lambda token, uid, text, video: sent.append((uid, text)) or True)
    settings = Settings(telegram_bot_token="t", telegram_allowed_user_ids="10,20")

    notify_job_finished(session, settings, job.id)
    notify_job_finished(session, settings, job.id)  # idempotent

    assert [uid for uid, _ in sent] == [10, 20]
    assert "кандидатов: 1" in sent[0][1]
    assert session.get(AppSetting, f"telegram_notified:{job.id}").value_json["delivered"] is True


def test_notify_ignores_non_terminal_jobs(session, monkeypatch):
    episode_id = _episode(session)
    job = Job(episode_id=episode_id, kind=JobKind.ANALYZE_EPISODE.value, status=JobStatus.RUNNING.value)
    session.add(job)
    session.flush()
    monkeypatch.setattr(notifications, "_deliver", lambda *a: (_ for _ in ()).throw(AssertionError("should not send")))

    notify_job_finished(session, Settings(telegram_bot_token="t", telegram_allowed_user_ids="10"), job.id)
