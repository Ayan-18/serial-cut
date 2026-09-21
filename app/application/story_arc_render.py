from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.candidate_editor import subtitle_cues_for_render
from app.application.narration import synthesize_story_arc_narration
from app.application.story_arc_render_ffmpeg import (
    _concat_segments,
    _crossfade_duration,
    _mix_narration,
    build_concat_args,
    build_crossfade_args,
    build_narration_mix_args,
    concat_list_text,
)
from app.application.story_arc_render_support import (
    _load_arc,
    _narration_path,
    _normalize_narration_mode,
    _raise_if_cancelled,
    _story_arc_render_fingerprint,
    _story_arc_slug,
    _safe_slug,
)
from app.infrastructure.atomic import replace_atomically, temp_sibling, write_text_atomically
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessResult, run_process
from app.media.rendering import RENDER_PRESETS, detect_nvenc, render_clip
from app.media.subtitles import render_ass
from app.models.entities import ClipCandidate, Episode, Season, StoryArcExport

# Re-exported: these all used to live in this module and a few tests/callers
# still import them from here. The ffmpeg concat/crossfade/narration-mix
# argument builders moved to story_arc_render_ffmpeg.py, the fingerprint and
# naming helpers to story_arc_render_support.py — neither of them touches
# `render_clip`/`detect_nvenc`, which is why they were safe to pull out of
# this file while `render_story_arc` itself stayed.
__all__ = [
    "StoryArcRenderResult",
    "render_story_arc",
    "build_concat_args",
    "concat_list_text",
    "build_crossfade_args",
    "build_narration_mix_args",
]


@dataclass(frozen=True)
class StoryArcRenderResult:
    story_arc_id: int
    export_id: int
    output_path: str
    metadata_path: str | None
    cover_path: str | None
    segment_count: int
    duration_seconds: float


def render_story_arc(
    session: Session,
    story_arc_id: int,
    settings: Settings,
    include_subtitles: bool = True,
    use_nvenc: bool | None = None,
    preset_name: str | None = None,
    loudnorm_two_pass: bool | None = None,
    force_rerender: bool = False,
    transition_style: str = "cut",
    include_narration: bool = True,
    narration_mode: str = "first_person",
    progress_callback: Callable[[int, int, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> StoryArcRenderResult:
    arc = _load_arc(session, story_arc_id)
    if not arc.segments:
        raise ValueError("В монтажном плане нет сегментов")
    preset = RENDER_PRESETS.get(preset_name or settings.render_preset, RENDER_PRESETS["youtube_shorts"])
    season = session.get(Season, arc.season_id)
    if season is None:
        raise ValueError("Сезон не найден")
    narration_path = _narration_path(arc)
    resolved_narration_mode = _normalize_narration_mode(arc, narration_mode, include_narration)
    narration_requested = bool(resolved_narration_mode != "none" and (arc.plan_json or {}).get("narration"))
    segment_durations = [max(0.0, item.end_time - item.start_time) for item in arc.segments]
    expected_duration = (
        _crossfade_duration(segment_durations) if transition_style == "fade" else sum(segment_durations)
    )
    if narration_requested:
        plan = dict(arc.plan_json or {})
        timeline_outdated = (
            plan.get("narration_timeline_version") != 2
            or abs(float(plan.get("narration_duration_seconds") or 0.0) - expected_duration) > 0.25
        )
        if narration_path is None or not narration_path.exists() or timeline_outdated:
            narration_audio = synthesize_story_arc_narration(
                session,
                arc.id,
                settings,
                runner=runner,
                target_duration_seconds=expected_duration,
                narration_mode=resolved_narration_mode,
            )
            narration_path = Path(narration_audio.audio_path)
    resolved_loudnorm = settings.render_loudnorm_two_pass if loudnorm_two_pass is None else loudnorm_two_pass
    render_fingerprint = _story_arc_render_fingerprint(
        session,
        arc,
        settings,
        include_subtitles=include_subtitles,
        preset_name=preset.name,
        loudnorm_two_pass=resolved_loudnorm,
        transition_style=transition_style,
        narration_path=narration_path if narration_requested else None,
        narration_mode=resolved_narration_mode,
        encoder_preference=use_nvenc,
    )
    existing = session.scalar(
        select(StoryArcExport)
        .where(
            StoryArcExport.story_arc_id == story_arc_id,
            StoryArcExport.render_fingerprint == render_fingerprint,
            StoryArcExport.status == "completed",
        )
        .order_by(StoryArcExport.version.desc(), StoryArcExport.id.desc())
    )
    if existing is not None and Path(existing.output_path).exists() and not force_rerender:
        return StoryArcRenderResult(
            arc.id,
            existing.id,
            existing.output_path,
            existing.metadata_path,
            existing.cover_path,
            existing.segment_count,
            round(expected_duration, 3),
        )
    version = int(
        session.scalar(
            select(func.coalesce(func.max(StoryArcExport.version), 0)).where(
                StoryArcExport.story_arc_id == arc.id
            )
        )
        or 0
    ) + 1
    output_slug = (
        f"{_story_arc_slug(arc)}-v{version:03}-{render_fingerprint[:8]}-{uuid4().hex[:8]}"
    )
    output_dir = settings.output_dir / _safe_slug(season.title) / f"story-arc-{arc.id}"
    segment_dir = settings.cache_dir / "story-arc-segments" / str(arc.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    segment_dir.mkdir(parents=True, exist_ok=True)
    resolved_nvenc = detect_nvenc(settings.ffmpeg_path, runner) if use_nvenc is None else use_nvenc

    total_steps = len(arc.segments) + 2 + (1 if narration_requested else 0)
    segment_paths, segment_durations, segment_metadata, first_cover = _render_segments(
        session,
        arc,
        settings,
        segment_dir,
        output_slug,
        include_subtitles,
        resolved_nvenc,
        preset.name,
        resolved_loudnorm,
        runner,
        cancel_check,
        progress_callback,
        total_steps,
    )

    output_path = output_dir / f"{output_slug}.mp4"
    _raise_if_cancelled(cancel_check)
    final_duration = _concat_segments(
        settings.ffmpeg_path,
        segment_paths,
        output_path,
        runner,
        transition_style=transition_style,
        durations=segment_durations,
        preset=preset,
        use_nvenc=resolved_nvenc,
    )
    if progress_callback is not None:
        progress_callback(len(arc.segments) + 1, total_steps, "Сегменты склеены")

    if narration_requested:
        plan = dict(arc.plan_json or {})
        timeline_outdated = (
            plan.get("narration_timeline_version") != 2
            or abs(float(plan.get("narration_duration_seconds") or 0.0) - final_duration) > 0.25
        )
        if narration_path is None or not narration_path.exists() or timeline_outdated:
            narration_audio = synthesize_story_arc_narration(
                session,
                arc.id,
                settings,
                runner=runner,
                target_duration_seconds=final_duration,
                narration_mode=resolved_narration_mode,
            )
            narration_path = Path(narration_audio.audio_path)
        _raise_if_cancelled(cancel_check)
        _mix_narration(settings.ffmpeg_path, output_path, narration_path, final_duration, runner)
        if progress_callback is not None:
            progress_callback(len(arc.segments) + 2, total_steps, "Озвучка добавлена")
    _raise_if_cancelled(cancel_check)
    metadata_path = output_dir / f"{output_slug}.json"
    metadata = {
        "story_arc_id": arc.id,
        "title": arc.title,
        "season_id": arc.season_id,
        "season": season.title,
        "output_format": arc.output_format,
        "preset_name": preset.name,
        "include_subtitles": include_subtitles,
        "segment_count": len(segment_paths),
        "duration_seconds": round(final_duration, 3),
        "transition_style": transition_style,
        "version": version,
        "render_fingerprint": render_fingerprint,
        "segments": segment_metadata,
        "narration": (arc.plan_json or {}).get("narration", []),
        "narration_mode": resolved_narration_mode,
    }
    metadata["narration_included"] = bool(narration_requested and narration_path and narration_path.exists())
    write_text_atomically(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2))
    cover_path = output_dir / f"{output_slug}.jpg"
    if first_cover is not None and first_cover.exists():
        temp_cover = temp_sibling(cover_path).with_suffix(".jpg")
        shutil.copyfile(first_cover, temp_cover)
        replace_atomically(temp_cover, cover_path)
    else:
        cover_path = None

    export = StoryArcExport(story_arc_id=arc.id, output_path=str(output_path))
    export.metadata_path = str(metadata_path)
    export.cover_path = str(cover_path) if cover_path else None
    export.width = preset.width
    export.height = preset.height
    export.include_subtitles = include_subtitles
    export.preset_name = preset.name
    export.segment_count = len(segment_paths)
    export.status = "completed"
    export.arc_revision = arc.edit_revision
    export.transition_style = transition_style
    export.narration_included = bool(metadata["narration_included"])
    export.version = version
    export.render_fingerprint = render_fingerprint
    arc.status = "rendered"
    session.add(export)
    session.flush()
    if progress_callback is not None:
        progress_callback(total_steps, total_steps, "StoryArc готов")
    return StoryArcRenderResult(
        arc.id,
        export.id,
        export.output_path,
        export.metadata_path,
        export.cover_path,
        export.segment_count,
        round(final_duration, 3),
    )


def _render_segments(
    session: Session,
    arc,
    settings: Settings,
    segment_dir: Path,
    output_slug: str,
    include_subtitles: bool,
    use_nvenc: bool,
    preset_name: str,
    loudnorm_two_pass: bool,
    runner: Callable[[list[str], int], ProcessResult],
    cancel_check: Callable[[], bool] | None,
    progress_callback: Callable[[int, int, str], None] | None,
    total_steps: int,
) -> tuple[list[Path], list[float], list[dict], Path | None]:
    """Render every StoryArc segment to its own clip. Kept in this module
    (rather than moved out with the other helpers) because it is the thing
    that actually calls `render_clip`, which tests monkeypatch on this exact
    module."""
    segment_paths: list[Path] = []
    segment_durations: list[float] = []
    segment_metadata: list[dict] = []
    first_cover: Path | None = None
    for index, segment in enumerate(arc.segments, start=1):
        _raise_if_cancelled(cancel_check)
        candidate = session.get(ClipCandidate, segment.candidate_id) if segment.candidate_id else None
        episode = session.get(Episode, segment.episode_id)
        if episode is None:
            raise ValueError(f"Серия сегмента {segment.id} не найдена")
        crop_mode = candidate.crop_mode if candidate else "center-crop"
        crop_offset_x = candidate.crop_offset_x if candidate else 0.0
        crop_scale = candidate.crop_scale if candidate else 1.0
        crop_keyframes = candidate.crop_keyframes_json if candidate else []
        cues = (
            subtitle_cues_for_render(
                session,
                candidate,
                settings.subtitle_show_speaker_names,
                start_time=segment.start_time,
                end_time=segment.end_time,
            )
            if candidate
            else []
        )
        subtitle_text = (
            render_ass(
                cues,
                font_name=settings.subtitle_font_name,
                font_size=settings.subtitle_font_size,
                safe_zone=settings.subtitle_safe_zone,
                animate=settings.subtitle_animate,
            )
            if include_subtitles
            else None
        )
        session.commit()
        artifacts = render_clip(
            settings.ffmpeg_path,
            Path(episode.file_path),
            segment_dir,
            f"{output_slug}-part-{segment.sort_order:02}",
            segment.start_time,
            segment.end_time,
            crop_mode,
            subtitle_text,
            {
                "story_arc_id": arc.id,
                "story_arc_title": arc.title,
                "story_arc_segment_id": segment.id,
                "episode_id": episode.id,
                "episode": episode.file_name,
                "candidate_id": segment.candidate_id,
                "title": segment.title,
                "start_time": segment.start_time,
                "end_time": segment.end_time,
                "role": segment.role,
            },
            crop_offset_x=crop_offset_x,
            crop_scale=crop_scale,
            crop_keyframes=crop_keyframes,
            use_nvenc=use_nvenc,
            preset_name=preset_name,
            loudnorm_two_pass=loudnorm_two_pass,
            runner=runner,
            audio_stream_index=episode.selected_audio_stream_index,
            face_detector_model=settings.face_detector_model,
        )
        segment_paths.append(artifacts.output_path)
        segment_durations.append(segment.end_time - segment.start_time)
        if first_cover is None:
            first_cover = artifacts.cover_path
        segment_metadata.append(
            {
                "segment_id": segment.id,
                "episode_id": episode.id,
                "episode": episode.file_name,
                "candidate_id": segment.candidate_id,
                "start_time": segment.start_time,
                "end_time": segment.end_time,
                "title": segment.title,
                "role": segment.role,
                "output_path": str(artifacts.output_path),
            }
        )
        if progress_callback is not None:
            progress_callback(index, total_steps, f"Сегмент {index} из {len(arc.segments)}")
    return segment_paths, segment_durations, segment_metadata, first_cover
