from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.application.deletion import (
    ResourceBusyError,
    delete_episode,
    delete_season,
    purge_artifacts,
)
from app.application.importer import import_season
from app.application.story_arcs import StoryArcPlanRequest, add_candidate_to_story_arc, create_story_arc_plan
from app.domain.enums import JobStatus
from app.infrastructure.config import Settings
from app.models.entities import (
    CandidateSubtitle,
    ClipCandidate,
    Episode,
    Job,
    JobStage,
    Scene,
    Season,
    StoryArc,
    StoryArcSegment,
    TranscriptSegment,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        cache_dir=tmp_path / "cache",
        output_dir=tmp_path / "output",
        characters_dir=tmp_path / "characters",
    )


def _episode_with_derived(session, tmp_path: Path, name: str = "episode.mkv") -> Episode:
    season_dir = tmp_path / "season"
    season_dir.mkdir(exist_ok=True)
    (season_dir / name).write_bytes(name.encode() + b"-video-bytes")
    result = import_season(session, season_dir)
    episode = session.get(Episode, result.episode_ids[-1])
    candidate = ClipCandidate(
        episode_id=episode.id,
        start_time=5,
        end_time=15,
        title="Момент",
        description="Описание",
        moment_type="другое",
        score=88,
        scores_json={},
        rationale="Понятен отдельно",
        problems_json=[],
    )
    session.add(candidate)
    session.flush()
    session.add(CandidateSubtitle(candidate_id=candidate.id, start_time=5, end_time=7, text="Реплика"))
    session.add(TranscriptSegment(episode_id=episode.id, start_time=0, end_time=4, text="Начало"))
    session.add(Scene(episode_id=episode.id, start_time=0, end_time=10))
    job = Job(episode_id=episode.id, status=JobStatus.COMPLETED.value)
    session.add(job)
    session.flush()
    session.add(JobStage(job_id=job.id, name="stage2_media", status=JobStatus.COMPLETED.value))
    session.flush()
    return episode


def test_delete_episode_removes_all_dependent_rows(session, tmp_path: Path):
    episode = _episode_with_derived(session, tmp_path)
    episode_id = episode.id

    delete_episode(session, episode_id, _settings(tmp_path))
    session.commit()

    assert session.get(Episode, episode_id) is None
    assert session.scalars(select(ClipCandidate).where(ClipCandidate.episode_id == episode_id)).all() == []
    assert session.scalars(select(CandidateSubtitle)).all() == []
    assert session.scalars(select(TranscriptSegment).where(TranscriptSegment.episode_id == episode_id)).all() == []
    assert session.scalars(select(Scene).where(Scene.episode_id == episode_id)).all() == []
    assert session.scalars(select(Job).where(Job.episode_id == episode_id)).all() == []
    assert session.scalars(select(JobStage)).all() == []


def test_delete_episode_refuses_while_a_job_is_active(session, tmp_path: Path):
    episode = _episode_with_derived(session, tmp_path)
    session.add(Job(episode_id=episode.id, status=JobStatus.QUEUED.value))
    session.flush()

    with pytest.raises(ResourceBusyError):
        delete_episode(session, episode.id, _settings(tmp_path))


def test_delete_episode_prunes_story_arc_segments(session, tmp_path: Path):
    episode = _episode_with_derived(session, tmp_path)
    candidate = session.scalars(
        select(ClipCandidate).where(ClipCandidate.episode_id == episode.id)
    ).first()
    arc = create_story_arc_plan(
        session,
        StoryArcPlanRequest(season_id=episode.season_id, title="Арка", prompt=""),
    )
    add_candidate_to_story_arc(session, arc.id, candidate.id)
    session.commit()
    assert session.scalars(select(StoryArcSegment)).all() != []

    delete_episode(session, episode.id, _settings(tmp_path))
    session.commit()

    assert session.scalars(select(StoryArcSegment)).all() == []
    assert session.get(StoryArc, arc.id) is not None


def test_delete_season_cascades_to_episodes_and_arcs(session, tmp_path: Path):
    episode = _episode_with_derived(session, tmp_path)
    season_id = episode.season_id
    create_story_arc_plan(
        session,
        StoryArcPlanRequest(season_id=season_id, title="Арка", prompt=""),
    )
    session.commit()

    artifacts = delete_season(session, season_id, _settings(tmp_path))
    session.commit()

    assert session.get(Season, season_id) is None
    assert session.scalars(select(Episode).where(Episode.season_id == season_id)).all() == []
    assert session.scalars(select(StoryArc).where(StoryArc.season_id == season_id)).all() == []
    assert isinstance(artifacts.trees, list)


def test_purge_artifacts_only_touches_files_inside_managed_roots(session, tmp_path: Path):
    settings = _settings(tmp_path)
    managed = settings.output_dir / "fingerprint" / "clip.mp4"
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"rendered")
    outside = tmp_path / "keep.mp4"
    outside.write_bytes(b"original source")

    episode = _episode_with_derived(session, tmp_path)
    artifacts = delete_episode(session, episode.id, settings)
    artifacts.files.append(str(managed))
    artifacts.files.append(str(outside))
    session.commit()
    purge_artifacts(artifacts, settings)

    assert not managed.exists()
    assert outside.exists()
