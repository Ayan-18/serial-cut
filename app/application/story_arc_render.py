from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.application.candidate_editor import subtitle_cues_for_render
from app.application.narration import synthesize_story_arc_narration
from app.infrastructure.atomic import replace_atomically, temp_sibling, write_text_atomically
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessCancelledError, ProcessResult, run_process
from app.media.rendering import RENDER_PRESETS, detect_nvenc, render_clip
from app.media.subtitles import render_ass
from app.models.entities import ClipCandidate, Episode, Season, StoryArc, StoryArcExport


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
    progress_callback: Callable[[int, int, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> StoryArcRenderResult:
    arc = _load_arc(session, story_arc_id)
    existing = session.scalar(
        select(StoryArcExport)
        .where(StoryArcExport.story_arc_id == story_arc_id)
        .order_by(StoryArcExport.created_at.desc())
    )
    narration_path = _narration_path(arc)
    narration_requested = bool(include_narration and (arc.plan_json or {}).get("narration"))
    reusable = (
        existing is not None
        and existing.status == "completed"
        and existing.arc_revision == arc.edit_revision
        and existing.include_subtitles == include_subtitles
        and existing.preset_name == (preset_name or settings.render_preset)
        and existing.transition_style == transition_style
        and existing.narration_included == narration_requested
        and Path(existing.output_path).exists()
    )
    if reusable and not force_rerender:
        return StoryArcRenderResult(
            arc.id,
            existing.id,
            existing.output_path,
            existing.metadata_path,
            existing.cover_path,
            existing.segment_count,
            arc.total_duration_seconds,
        )
    if not arc.segments:
        raise ValueError("В монтажном плане нет сегментов")

    preset = RENDER_PRESETS.get(preset_name or settings.render_preset, RENDER_PRESETS["youtube_shorts"])
    season = session.get(Season, arc.season_id)
    if season is None:
        raise ValueError("Сезон не найден")
    output_slug = _story_arc_slug(arc)
    output_dir = settings.output_dir / _safe_slug(season.title) / f"story-arc-{arc.id}"
    segment_dir = settings.cache_dir / "story-arc-segments" / str(arc.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    segment_dir.mkdir(parents=True, exist_ok=True)
    resolved_nvenc = detect_nvenc(settings.ffmpeg_path, runner) if use_nvenc is None else use_nvenc
    segment_paths: list[Path] = []
    segment_durations: list[float] = []
    segment_metadata: list[dict] = []
    first_cover: Path | None = None

    total_steps = len(arc.segments) + 2 + (1 if narration_requested else 0)
    for index, segment in enumerate(arc.segments, start=1):
        _raise_if_cancelled(cancel_check)
        candidate = session.get(ClipCandidate, segment.candidate_id) if segment.candidate_id else None
        episode = session.get(Episode, segment.episode_id)
        if episode is None:
            raise ValueError(f"Серия сегмента {segment.id} не найдена")
        crop_mode = candidate.crop_mode if candidate else "blurred-background"
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
            use_nvenc=resolved_nvenc,
            preset_name=preset.name,
            loudnorm_two_pass=settings.render_loudnorm_two_pass if loudnorm_two_pass is None else loudnorm_two_pass,
            runner=runner,
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

    output_path = output_dir / f"{output_slug}.mp4"
    _raise_if_cancelled(cancel_check)
    _concat_segments(
        settings.ffmpeg_path,
        segment_paths,
        output_path,
        runner,
        transition_style=transition_style,
        durations=segment_durations,
    )
    if progress_callback is not None:
        progress_callback(len(arc.segments) + 1, total_steps, "Сегменты склеены")

    if narration_requested:
        if narration_path is None or not narration_path.exists():
            narration_audio = synthesize_story_arc_narration(session, arc.id, settings, runner=runner)
            narration_path = Path(narration_audio.audio_path)
        _raise_if_cancelled(cancel_check)
        _mix_narration(settings.ffmpeg_path, output_path, narration_path, runner)
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
        "duration_seconds": arc.total_duration_seconds,
        "transition_style": transition_style,
        "segments": segment_metadata,
        "narration": (arc.plan_json or {}).get("narration", []),
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

    export = existing or StoryArcExport(story_arc_id=arc.id, output_path=str(output_path))
    export.output_path = str(output_path)
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
    arc.status = "rendered"
    if existing is None:
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
        arc.total_duration_seconds,
    )


def build_concat_args(ffmpeg_path: str, concat_list_path: Path, output_path: Path) -> list[str]:
    return [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def concat_list_text(paths: list[Path]) -> str:
    return "".join(f"file '{_concat_path(path)}'\n" for path in paths)


def _concat_segments(
    ffmpeg_path: str,
    segment_paths: list[Path],
    output_path: Path,
    runner: Callable[[list[str], int], ProcessResult],
    transition_style: str = "cut",
    durations: list[float] | None = None,
) -> None:
    if not segment_paths:
        raise ValueError("Нет сегментов для склейки")
    temp_output = temp_sibling(output_path).with_suffix(".mp4")
    if transition_style == "fade" and len(segment_paths) > 1:
        result = runner(
            build_crossfade_args(ffmpeg_path, segment_paths, durations or [], temp_output),
            3600,
        )
    else:
        concat_list_path = output_path.with_suffix(".concat.txt")
        write_text_atomically(concat_list_path, concat_list_text(segment_paths))
        result = runner(build_concat_args(ffmpeg_path, concat_list_path, temp_output), 3600)
    if result.returncode != 0:
        temp_output.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "FFmpeg не смог склеить StoryArc")
    if temp_output.exists():
        replace_atomically(temp_output, output_path)


def build_crossfade_args(
    ffmpeg_path: str,
    paths: list[Path],
    durations: list[float],
    output_path: Path,
    fade_seconds: float = 0.25,
) -> list[str]:
    if len(paths) < 2 or len(durations) != len(paths):
        raise ValueError("Для плавной склейки нужны длительности всех сегментов")
    args = [ffmpeg_path, "-hide_banner", "-y"]
    for path in paths:
        args.extend(["-i", str(path)])
    filters: list[str] = []
    video_label = "0:v"
    audio_label = "0:a"
    elapsed = durations[0]
    for index in range(1, len(paths)):
        fade = min(fade_seconds, max(0.08, durations[index - 1] / 4), max(0.08, durations[index] / 4))
        video_out = f"v{index}"
        audio_out = f"a{index}"
        offset = max(0.0, elapsed - fade)
        filters.append(
            f"[{video_label}][{index}:v]xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}[{video_out}]"
        )
        filters.append(f"[{audio_label}][{index}:a]acrossfade=d={fade:.3f}:c1=tri:c2=tri[{audio_out}]")
        video_label = video_out
        audio_label = audio_out
        elapsed += durations[index] - fade
    args.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{video_label}]",
            "-map",
            f"[{audio_label}]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return args


def _mix_narration(
    ffmpeg_path: str,
    video_path: Path,
    narration_path: Path,
    runner: Callable[[list[str], int], ProcessResult],
) -> None:
    temp_output = temp_sibling(video_path).with_suffix(".mp4")
    args = [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(narration_path),
        "-filter_complex",
        "[0:a]volume=0.32[base];[1:a]aresample=async=1:first_pts=0,volume=1.0[voice];"
        "[base][voice]amix=inputs=2:duration=first:dropout_transition=2[a]",
        "-map",
        "0:v:0",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(temp_output),
    ]
    result = runner(args, 3600)
    if result.returncode != 0:
        temp_output.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "FFmpeg не смог добавить озвучку")
    if temp_output.exists():
        replace_atomically(temp_output, video_path)


def _narration_path(arc: StoryArc) -> Path | None:
    value = (arc.plan_json or {}).get("narration_audio_path")
    return Path(value) if isinstance(value, str) and value.strip() else None


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise ProcessCancelledError("Рендер StoryArc остановлен пользователем")


def _load_arc(session: Session, story_arc_id: int) -> StoryArc:
    arc = session.scalar(
        select(StoryArc)
        .options(selectinload(StoryArc.segments), selectinload(StoryArc.exports))
        .where(StoryArc.id == story_arc_id)
    )
    if arc is None:
        raise ValueError("Арка не найдена")
    return arc


def _story_arc_slug(arc: StoryArc) -> str:
    return _safe_slug(f"story-arc-{arc.id}-{arc.title}")[:120].rstrip("-")


def _safe_slug(value: str) -> str:
    slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", value)
    slug = re.sub(r"\s*-\s*", "-", slug)
    slug = re.sub(r"\s+", " ", slug).strip(" .-_")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "story-arc"


def _concat_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "'\\''")
