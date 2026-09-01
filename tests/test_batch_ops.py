from __future__ import annotations

from itertools import count as _count

from app.models.entities import ClipCandidate, Episode, Job, Season

_seq = _count(1)


def _episode_with_candidates(session, count: int, status: str = "new") -> tuple[int, list[int]]:
    marker = next(_seq)
    season = Season(title="S", root_path=f"C:/s{marker}")
    session.add(season)
    session.flush()
    episode = Episode(
        season_id=season.id,
        file_path="C:/s/e.mkv",
        file_name="e.mkv",
        fingerprint=f"fp-batch-{marker}",
        size_bytes=1,
        modified_ns=1,
        duration_seconds=600.0,
    )
    session.add(episode)
    session.flush()
    ids = []
    for index in range(count):
        candidate = ClipCandidate(
            episode_id=episode.id,
            start_time=10 + index * 60,
            end_time=45 + index * 60,
            title=f"Момент {index}",
            description="d",
            moment_type="другое",
            score=80,
            scores_json={},
            rationale="r",
            problems_json=[],
            status=status,
        )
        session.add(candidate)
        session.flush()
        ids.append(candidate.id)
    return episode.id, ids


def test_batch_review_approves_known_candidates_and_reports_skips(session):
    episode_id, ids = _episode_with_candidates(session, 3)

    from app.application.batch_ops import batch_review_candidates

    outcome = batch_review_candidates(session, episode_id, [*ids, 9999], "approve")

    assert outcome.requested == 4
    assert set(outcome.succeeded) == set(ids)
    assert outcome.skipped == [{"candidate_id": 9999, "reason": "не найден в этой серии"}]
    assert all(session.get(ClipCandidate, cid).status == "approved" for cid in ids)


def test_batch_render_job_only_enqueues_approved_candidates(session):
    episode_id, ids = _episode_with_candidates(session, 2, status="approved")
    _, new_ids = _episode_with_candidates(session, 1, status="new")

    from app.application.batch_ops import batch_enqueue_candidate_renders

    outcome = batch_enqueue_candidate_renders(
        session, [*ids, *new_ids], {"include_subtitles": True}
    )

    assert set(outcome.succeeded) == set(ids)
    assert outcome.skipped == [{"candidate_id": new_ids[0], "reason": "кандидат не принят"}]
    assert len(outcome.job_ids) == 2
    assert session.query(Job).count() == 2


def test_batch_render_job_is_idempotent(session):
    episode_id, ids = _episode_with_candidates(session, 1, status="approved")

    from app.application.batch_ops import batch_enqueue_candidate_renders

    first = batch_enqueue_candidate_renders(session, ids, {"include_subtitles": True})
    second = batch_enqueue_candidate_renders(session, ids, {"include_subtitles": True})

    assert first.job_ids == second.job_ids
    assert session.query(Job).count() == 1


def test_batch_review_endpoint(api_client):
    session = api_client.db
    episode_id, ids = _episode_with_candidates(session, 2)
    session.commit()

    response = api_client.post(
        f"/api/episodes/{episode_id}/candidates/batch-review",
        json={"candidate_ids": ids, "decision": "reject"},
    )

    assert response.status_code == 200
    assert set(response.json()["succeeded"]) == set(ids)
