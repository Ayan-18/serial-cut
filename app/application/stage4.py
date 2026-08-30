from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import EpisodeStage
from app.infrastructure.config import Settings
from app.media.rendering import detect_nvenc, render_clip
from app.media.subtitles import cues_for_range, cues_for_words, render_ass
from app.models.entities import ClipCandidate, Episode, Export, TranscriptSegment, WordTimestamp


@dataclass(frozen=True)
class RenderResult:
    candidate_id: int
    export_id: int
    output_path: str
    subtitle_path: str | None
    cover_path: str | None


def render_candidate(
    session: Session,
    candidate_id: int,
    settings: Settings,
    include_subtitles: bool = True,
    use_nvenc: bool | None = None,
    preset_name: str | None = None,
    loudnorm_two_pass: bool | None = None,
    force_rerender: bool = False,
) -> RenderResult:
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    episode = session.get(Episode, candidate.episode_id)
    if episode is None:
        raise ValueError(f"Episode {candidate.episode_id} not found")
    existing = session.scalar(select(Export).where(Export.candidate_id == candidate_id))
    if existing is not None and not force_rerender:
        return RenderResult(candidate_id, existing.id, existing.output_path, existing.subtitle_path, existing.cover_path)

    segments = session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode.id)
        .order_by(TranscriptSegment.start_time)
    ).all()
    words = session.scalars(
        select(WordTimestamp)
        .join(TranscriptSegment, WordTimestamp.segment_id == TranscriptSegment.id)
        .where(TranscriptSegment.episode_id == episode.id)
        .order_by(WordTimestamp.start_time)
    ).all()
    cues = (
        cues_for_words(words, candidate.start_time, candidate.end_time)
        if words
        else cues_for_range(segments, candidate.start_time, candidate.end_time)
    )
    subtitle_text = (
        render_ass(cues, font_name=settings.subtitle_font_name, font_size=settings.subtitle_font_size)
        if include_subtitles
        else None
    )
    slug = f"episode-{episode.id}-candidate-{candidate.id}"
    resolved_nvenc = detect_nvenc(settings.ffmpeg_path) if use_nvenc is None else use_nvenc
    artifacts = render_clip(
        settings.ffmpeg_path,
        Path(episode.file_path),
        settings.output_dir / episode.fingerprint,
        slug,
        candidate.start_time,
        candidate.end_time,
        candidate.crop_mode,
        subtitle_text,
        {
            "episode_id": episode.id,
            "candidate_id": candidate.id,
            "title": candidate.title,
            "score": candidate.score,
            "crop_mode": candidate.crop_mode,
            "start_time": candidate.start_time,
            "end_time": candidate.end_time,
        },
        use_nvenc=resolved_nvenc,
        preset_name=preset_name or settings.render_preset,
        loudnorm_two_pass=settings.render_loudnorm_two_pass if loudnorm_two_pass is None else loudnorm_two_pass,
    )
    export = existing or Export(candidate_id=candidate.id, output_path=str(artifacts.output_path))
    export.output_path = str(artifacts.output_path)
    export.metadata_path = str(artifacts.metadata_path)
    export.subtitle_path = str(artifacts.subtitle_path) if artifacts.subtitle_path else None
    export.cover_path = str(artifacts.cover_path) if artifacts.cover_path else None
    if existing is None:
        session.add(export)
    candidate.status = "rendered"
    episode.stage = EpisodeStage.RENDERED.value
    session.flush()
    return RenderResult(candidate.id, export.id, export.output_path, export.subtitle_path, export.cover_path)
