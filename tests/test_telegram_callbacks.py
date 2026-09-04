from __future__ import annotations

from app.bot.callbacks import handle_candidate_callback, is_user_allowed
from app.domain.enums import JobKind, JobStatus
from app.infrastructure.config import Settings
from app.models.entities import ClipCandidate, Job


def test_whitelist_only_allows_configured_user_ids():
    assert is_user_allowed(10, [10, 20])
    assert not is_user_allowed(30, [10, 20])


def test_telegram_callback_is_idempotent_for_approve(session):
    candidate = ClipCandidate(
        episode_id=1,
        start_time=0,
        end_time=35,
        title="Тест",
        description="Описание",
        moment_type="другое",
        score=90,
        scores_json={},
        rationale="Понятен",
        problems_json=[],
    )
    session.add(candidate)
    session.flush()

    first = handle_candidate_callback(session, Settings(), "abc", "approve", candidate.id)
    second = handle_candidate_callback(session, Settings(), "abc", "approve", candidate.id)

    assert first.message == second.message
    assert candidate.status == "approved"


def _candidate(session) -> ClipCandidate:
    candidate = ClipCandidate(
        episode_id=1,
        start_time=0,
        end_time=40,
        title="Рендер",
        description="d",
        moment_type="другое",
        score=88,
        scores_json={},
        rationale="r",
        problems_json=[],
    )
    session.add(candidate)
    session.flush()
    return candidate


def test_render_callback_enqueues_a_job_instead_of_rendering_inline(session):
    candidate = _candidate(session)

    result = handle_candidate_callback(session, Settings(), "q1", "render", candidate.id)

    assert result.status == "queued"
    jobs = session.query(Job).filter(Job.kind == JobKind.RENDER_CLIP.value).all()
    assert len(jobs) == 1
    assert jobs[0].status == JobStatus.QUEUED.value
    assert jobs[0].payload["candidate_id"] == candidate.id


def test_legacy_export_callback_still_maps_to_a_render_job(session):
    candidate = _candidate(session)

    result = handle_candidate_callback(session, Settings(), "q2", "export", candidate.id)

    assert result.action == "render"
    assert session.query(Job).filter(Job.kind == JobKind.RENDER_CLIP.value).count() == 1

