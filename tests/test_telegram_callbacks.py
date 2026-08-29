from __future__ import annotations

from app.bot.callbacks import handle_candidate_callback, is_user_allowed
from app.infrastructure.config import Settings
from app.models.entities import ClipCandidate


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

