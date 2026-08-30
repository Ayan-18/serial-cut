from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import EpisodeStage
from app.infrastructure.config import Settings
from app.media.rendering import detect_nvenc, render_clip
from app.application.candidate_editor import subtitle_cues_for_render
from app.media.subtitles import render_ass
from app.models.entities import ClipCandidate, Episode, Export


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

    cues = subtitle_cues_for_render(
        session,
        candidate,
        show_speaker_names=settings.subtitle_show_speaker_names,
    )
    subtitle_text = (
        render_ass(cues, font_name=settings.subtitle_font_name, font_size=settings.subtitle_font_size)
        if include_subtitles
        else None
    )
    session.commit()
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
            "crop_keyframes": candidate.crop_keyframes_json,
            "start_time": candidate.start_time,
            "end_time": candidate.end_time,
        },
        crop_offset_x=candidate.crop_offset_x,
        crop_scale=candidate.crop_scale,
        crop_keyframes=candidate.crop_keyframes_json,
        use_nvenc=resolved_nvenc,
        preset_name=preset_name or settings.render_preset,
        loudnorm_two_pass=settings.render_loudnorm_two_pass if loudnorm_two_pass is None else loudnorm_two_pass,
    )
    export = existing or Export(candidate_id=candidate.id, output_path=str(artifacts.output_path))
    export.output_path = str(artifacts.output_path)
    export.metadata_path = str(artifacts.metadata_path)
    export.subtitle_path = str(artifacts.subtitle_path) if artifacts.subtitle_path else None
    export.cover_path = str(artifacts.cover_path) if artifacts.cover_path else None
    export.include_subtitles = include_subtitles
    export.preset_name = preset_name or settings.render_preset
    export.status = "completed"
    candidate.thumbnail_path = export.cover_path
    if existing is None:
        session.add(export)
    candidate.status = "rendered"
    episode.stage = EpisodeStage.RENDERED.value
    session.commit()
    return RenderResult(candidate.id, export.id, export.output_path, export.subtitle_path, export.cover_path)
