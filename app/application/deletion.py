from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.application.derived_files import delete_derived_artifacts, delete_derived_tree
from app.application.story_arcs import delete_story_arc, prune_episode_from_story_arcs
from app.domain.enums import JobStatus
from app.infrastructure.config import Settings
from app.models.entities import (
    CandidateEditSnapshot,
    CandidateSubtitle,
    Character,
    ClipCandidate,
    Episode,
    EpisodeOutline,
    Export,
    Job,
    JobStage,
    MediaTrack,
    PublishingPlan,
    ReviewDecision,
    Scene,
    Season,
    SpeakerIdentity,
    StoryArc,
    TranscriptSegment,
    WordTimestamp,
)

_ACTIVE_JOB_STATUSES = (
    JobStatus.QUEUED.value,
    JobStatus.RUNNING.value,
    JobStatus.PAUSED.value,
    JobStatus.CANCEL_REQUESTED.value,
)


class ResourceBusyError(RuntimeError):
    """Raised when a season/episode still has an unfinished queue job."""


@dataclass
class DeletionArtifacts:
    """Derived files and directories to remove after the DB rows are gone."""

    files: list[str | None] = field(default_factory=list)
    trees: list[Path] = field(default_factory=list)

    def merge(self, other: "DeletionArtifacts") -> None:
        self.files.extend(other.files)
        self.trees.extend(other.trees)


def delete_episode(session: Session, episode_id: int, settings: Settings) -> DeletionArtifacts:
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise ValueError("Серия не найдена")
    _ensure_episode_idle(session, episode_id)
    artifacts = _episode_derived_artifacts(session, episode, settings)
    _delete_episode_rows(session, episode)
    session.flush()
    return artifacts


def delete_season(session: Session, season_id: int, settings: Settings) -> DeletionArtifacts:
    season = session.get(Season, season_id)
    if season is None:
        raise ValueError("Сезон не найден")
    episode_ids = list(
        session.scalars(select(Episode.id).where(Episode.season_id == season_id)).all()
    )
    for episode_id in episode_ids:
        _ensure_episode_idle(session, episode_id)

    artifacts = DeletionArtifacts()

    for arc_id in session.scalars(
        select(StoryArc.id).where(StoryArc.season_id == season_id)
    ).all():
        arc_artifacts = delete_story_arc(session, arc_id)
        artifacts.files.extend(arc_artifacts.paths)
        artifacts.trees.append(settings.cache_dir / "story-arc-segments" / str(arc_id))
        for plan_id in arc_artifacts.publishing_plan_ids:
            artifacts.trees.append(settings.output_dir / "publishing" / f"plan-{plan_id}")

    for plan_id in session.scalars(
        select(PublishingPlan.id).where(PublishingPlan.season_id == season_id)
    ).all():
        artifacts.trees.append(settings.output_dir / "publishing" / f"plan-{plan_id}")
    session.execute(delete(PublishingPlan).where(PublishingPlan.season_id == season_id))

    for photos in session.scalars(
        select(Character.photos_json).where(Character.season_id == season_id)
    ).all():
        artifacts.files.extend(photos or [])

    for episode_id in episode_ids:
        episode = session.get(Episode, episode_id)
        if episode is None:
            continue
        artifacts.merge(_episode_derived_artifacts(session, episode, settings))
        _delete_episode_rows(session, episode)

    session.delete(season)
    session.flush()
    return artifacts


def purge_artifacts(artifacts: DeletionArtifacts, settings: Settings) -> None:
    roots = [settings.output_dir, settings.cache_dir, settings.characters_dir]
    delete_derived_artifacts(list(artifacts.files), roots)
    for tree in artifacts.trees:
        delete_derived_tree(tree, roots)


def _ensure_episode_idle(session: Session, episode_id: int) -> None:
    active_job_id = session.scalar(
        select(Job.id)
        .where(Job.episode_id == episode_id, Job.status.in_(_ACTIVE_JOB_STATUSES))
        .limit(1)
    )
    if active_job_id is not None:
        raise ResourceBusyError(
            f"Серия обрабатывается задачей №{active_job_id}. Остановите её в очереди и повторите."
        )


def _episode_derived_artifacts(
    session: Session, episode: Episode, settings: Settings
) -> DeletionArtifacts:
    fingerprint = episode.fingerprint
    artifacts = DeletionArtifacts(
        trees=[
            settings.cache_dir / "episodes" / fingerprint,
            settings.cache_dir / "previews" / fingerprint,
            settings.cache_dir / "keyframes" / fingerprint,
            settings.output_dir / fingerprint,
        ]
    )
    artifacts.files.extend([episode.proxy_path, episode.audio_path])
    candidate_ids = list(
        session.scalars(
            select(ClipCandidate.id).where(ClipCandidate.episode_id == episode.id)
        ).all()
    )
    if candidate_ids:
        artifacts.files.extend(
            session.scalars(
                select(ClipCandidate.thumbnail_path).where(
                    ClipCandidate.id.in_(candidate_ids)
                )
            ).all()
        )
        for export in session.scalars(
            select(Export).where(Export.candidate_id.in_(candidate_ids))
        ).all():
            artifacts.files.extend(
                [
                    export.output_path,
                    export.metadata_path,
                    export.subtitle_path,
                    export.cover_path,
                ]
            )
    return artifacts


def _delete_episode_rows(session: Session, episode: Episode) -> None:
    episode_id = episode.id
    candidate_ids = list(
        session.scalars(
            select(ClipCandidate.id).where(ClipCandidate.episode_id == episode_id)
        ).all()
    )
    segment_ids = list(
        session.scalars(
            select(TranscriptSegment.id).where(TranscriptSegment.episode_id == episode_id)
        ).all()
    )
    job_ids = list(
        session.scalars(select(Job.id).where(Job.episode_id == episode_id)).all()
    )

    prune_episode_from_story_arcs(session, episode_id)

    if candidate_ids:
        session.execute(delete(Export).where(Export.candidate_id.in_(candidate_ids)))
        session.execute(
            delete(CandidateSubtitle).where(
                CandidateSubtitle.candidate_id.in_(candidate_ids)
            )
        )
        session.execute(
            delete(CandidateEditSnapshot).where(
                CandidateEditSnapshot.candidate_id.in_(candidate_ids)
            )
        )
        session.execute(
            delete(ReviewDecision).where(ReviewDecision.candidate_id.in_(candidate_ids))
        )
    if segment_ids:
        session.execute(
            delete(WordTimestamp).where(WordTimestamp.segment_id.in_(segment_ids))
        )
    if job_ids:
        session.execute(delete(JobStage).where(JobStage.job_id.in_(job_ids)))
        session.execute(delete(Job).where(Job.id.in_(job_ids)))

    session.execute(delete(SpeakerIdentity).where(SpeakerIdentity.episode_id == episode_id))
    session.execute(delete(ClipCandidate).where(ClipCandidate.episode_id == episode_id))
    session.execute(
        delete(TranscriptSegment).where(TranscriptSegment.episode_id == episode_id)
    )
    session.execute(delete(Scene).where(Scene.episode_id == episode_id))
    session.execute(delete(EpisodeOutline).where(EpisodeOutline.episode_id == episode_id))
    session.execute(delete(MediaTrack).where(MediaTrack.episode_id == episode_id))
    session.delete(episode)
