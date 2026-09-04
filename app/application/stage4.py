from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Callable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import EpisodeStage
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessResult, run_process
from app.media.rendering import RENDER_PRESETS, detect_nvenc, render_clip
from app.application.candidate_editor import subtitle_cues_for_render
from app.application.render_fingerprint import canonical_render_fingerprint, source_signature
from app.media.subtitles import render_ass
from app.models.entities import ClipCandidate, Episode, Export


@dataclass(frozen=True)
class RenderResult:
    candidate_id: int
    export_id: int
    output_path: str
    subtitle_path: str | None
    cover_path: str | None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreviewRenderResult:
    candidate_id: int
    output_path: str
    subtitle_path: str | None
    cover_path: str | None
    duration_seconds: float


def render_candidate(
    session: Session,
    candidate_id: int,
    settings: Settings,
    include_subtitles: bool = True,
    use_nvenc: bool | None = None,
    preset_name: str | None = None,
    loudnorm_two_pass: bool | None = None,
    force_rerender: bool = False,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> RenderResult:
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    episode = session.get(Episode, candidate.episode_id)
    if episode is None:
        raise ValueError(f"Episode {candidate.episode_id} not found")
    resolved_preset = preset_name or settings.render_preset
    cues = subtitle_cues_for_render(
        session,
        candidate,
        show_speaker_names=settings.subtitle_show_speaker_names,
    )
    subtitle_text = (
        render_ass(
            cues,
            font_name=settings.subtitle_font_name,
            font_size=settings.subtitle_font_size,
            safe_zone=settings.subtitle_safe_zone,
        )
        if include_subtitles
        else None
    )
    resolved_loudnorm = settings.render_loudnorm_two_pass if loudnorm_two_pass is None else loudnorm_two_pass
    render_fingerprint = canonical_render_fingerprint(
        {
            "kind": "candidate",
            "candidate_id": candidate.id,
            "candidate_revision": candidate.edit_revision,
            "source": source_signature(Path(episode.file_path)),
            "episode_fingerprint": episode.fingerprint,
            "audio_stream_index": episode.selected_audio_stream_index,
            "range": [candidate.start_time, candidate.end_time],
            "crop": {
                "mode": candidate.crop_mode,
                "offset_x": candidate.crop_offset_x,
                "scale": candidate.crop_scale,
                "keyframes": candidate.crop_keyframes_json,
            },
            "subtitles": subtitle_text,
            "subtitle_style": {
                "font": settings.subtitle_font_name,
                "size": settings.subtitle_font_size,
                "safe_zone": settings.subtitle_safe_zone,
                "speaker_names": settings.subtitle_show_speaker_names,
            },
            "include_subtitles": include_subtitles,
            "preset": resolved_preset,
            "loudnorm_two_pass": resolved_loudnorm,
            "encoder_preference": use_nvenc,
        }
    )
    existing = session.scalar(
        select(Export)
        .where(
            Export.candidate_id == candidate_id,
            Export.render_fingerprint == render_fingerprint,
            Export.status == "completed",
        )
        .order_by(Export.version.desc(), Export.id.desc())
    )
    if existing is not None and Path(existing.output_path).exists() and not force_rerender:
        return RenderResult(
            candidate_id,
            existing.id,
            existing.output_path,
            existing.subtitle_path,
            existing.cover_path,
        )

    session.commit()
    version = int(
        session.scalar(select(func.coalesce(func.max(Export.version), 0)).where(Export.candidate_id == candidate.id))
        or 0
    ) + 1
    slug = (
        f"{export_slug(settings.export_filename_template, episode, candidate)}-"
        f"v{version:03}-{render_fingerprint[:8]}-{uuid4().hex[:8]}"
    )
    resolved_nvenc = detect_nvenc(settings.ffmpeg_path, runner) if use_nvenc is None else use_nvenc
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
            "version": version,
            "render_fingerprint": render_fingerprint,
            "audio_stream_index": episode.selected_audio_stream_index,
        },
        crop_offset_x=candidate.crop_offset_x,
        crop_scale=candidate.crop_scale,
        crop_keyframes=candidate.crop_keyframes_json,
        use_nvenc=resolved_nvenc,
        preset_name=resolved_preset,
        loudnorm_two_pass=resolved_loudnorm,
        runner=runner,
        audio_stream_index=episode.selected_audio_stream_index,
        face_detector_model=settings.face_detector_model,
    )
    export = Export(candidate_id=candidate.id, output_path=str(artifacts.output_path))
    export.metadata_path = str(artifacts.metadata_path)
    export.subtitle_path = str(artifacts.subtitle_path) if artifacts.subtitle_path else None
    export.cover_path = str(artifacts.cover_path) if artifacts.cover_path else None
    export.include_subtitles = include_subtitles
    export.preset_name = resolved_preset
    export.status = "completed"
    export.candidate_revision = candidate.edit_revision
    export.version = version
    export.render_fingerprint = render_fingerprint
    preset = RENDER_PRESETS.get(resolved_preset, RENDER_PRESETS["youtube_shorts"])
    export.width = preset.width
    export.height = preset.height
    candidate.thumbnail_path = export.cover_path
    session.add(export)
    candidate.status = "rendered"
    episode.stage = EpisodeStage.RENDERED.value
    session.commit()
    return RenderResult(
        candidate.id, export.id, export.output_path, export.subtitle_path, export.cover_path, artifacts.warnings
    )


def render_candidate_preview(
    session: Session,
    candidate_id: int,
    settings: Settings,
    include_subtitles: bool = True,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> PreviewRenderResult:
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    episode = session.get(Episode, candidate.episode_id)
    if episode is None:
        raise ValueError(f"Episode {candidate.episode_id} not found")
    cues = subtitle_cues_for_render(
        session,
        candidate,
        show_speaker_names=settings.subtitle_show_speaker_names,
    )
    subtitle_text = (
        render_ass(
            cues,
            font_name=settings.subtitle_font_name,
            font_size=max(24, settings.subtitle_font_size // 2),
            play_res_x=540,
            play_res_y=960,
            safe_zone=settings.subtitle_safe_zone,
        )
        if include_subtitles
        else None
    )
    session.commit()
    slug = f"preview-episode-{episode.id}-candidate-{candidate.id}"
    artifacts = render_clip(
        settings.ffmpeg_path,
        Path(episode.file_path),
        settings.cache_dir / "previews" / episode.fingerprint,
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
            "preview": True,
            "crop_mode": candidate.crop_mode,
            "crop_keyframes": candidate.crop_keyframes_json,
            "start_time": candidate.start_time,
            "end_time": candidate.end_time,
        },
        crop_offset_x=candidate.crop_offset_x,
        crop_scale=candidate.crop_scale,
        crop_keyframes=candidate.crop_keyframes_json,
        use_nvenc=False,
        preset_name="preview",
        loudnorm_two_pass=False,
        runner=runner,
        audio_stream_index=episode.selected_audio_stream_index,
        face_detector_model=settings.face_detector_model,
    )
    return PreviewRenderResult(
        candidate.id,
        str(artifacts.output_path),
        str(artifacts.subtitle_path) if artifacts.subtitle_path else None,
        str(artifacts.cover_path) if artifacts.cover_path else None,
        round(candidate.end_time - candidate.start_time, 3),
    )


def export_slug(template: str, episode: Episode, candidate: ClipCandidate) -> str:
    values = {
        "episode": Path(episode.file_name).stem,
        "episode_id": episode.id,
        "candidate": candidate.id,
        "candidate_id": candidate.id,
        "title": candidate.title,
        "score": candidate.score,
        "moment_type": candidate.moment_type,
        "start": f"{candidate.start_time:.1f}",
        "end": f"{candidate.end_time:.1f}",
    }
    try:
        raw = template.format(**values)
    except (KeyError, IndexError, ValueError):
        raw = "{episode}_clip-{candidate}_{title}_score-{score}".format(**values)
    slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", raw)
    slug = re.sub(r"\s*-\s*", "-", slug)
    slug = re.sub(r"-+_", "_", slug)
    slug = re.sub(r"_-+", "_", slug)
    slug = re.sub(r"\s+", " ", slug).strip(" .-_")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = f"episode-{episode.id}-candidate-{candidate.id}"
    return slug[:120].rstrip(" .-_")
