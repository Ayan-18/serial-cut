from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.application.candidate_editor import subtitle_cues_for_render
from app.application.narration import synthesize_story_arc_narration
from app.application.render_fingerprint import (
    canonical_render_fingerprint,
    small_file_sha256,
    source_signature,
)
from app.infrastructure.atomic import replace_atomically, temp_sibling, write_text_atomically
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessCancelledError, ProcessResult, run_process
from app.media.rendering import RENDER_PRESETS, RenderPresetConfig, detect_nvenc, render_clip
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
    segment_paths: list[Path] = []
    segment_durations = []
    segment_metadata: list[dict] = []
    first_cover: Path | None = None

    total_steps = len(arc.segments) + 2 + (1 if narration_requested else 0)
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
            loudnorm_two_pass=resolved_loudnorm,
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
    preset: RenderPresetConfig | None = None,
    use_nvenc: bool = False,
) -> float:
    if not segment_paths:
        raise ValueError("Нет сегментов для склейки")
    temp_output = temp_sibling(output_path).with_suffix(".mp4")
    if transition_style == "fade" and len(segment_paths) > 1:
        resolved_durations = durations or []
        result = runner(
            build_crossfade_args(
                ffmpeg_path,
                segment_paths,
                resolved_durations,
                temp_output,
                preset=preset,
                use_nvenc=use_nvenc,
            ),
            3600,
        )
        if result.returncode != 0 and use_nvenc:
            temp_output.unlink(missing_ok=True)
            result = runner(
                build_crossfade_args(
                    ffmpeg_path,
                    segment_paths,
                    resolved_durations,
                    temp_output,
                    preset=preset,
                    use_nvenc=False,
                ),
                3600,
            )
        output_duration = _crossfade_duration(resolved_durations)
    else:
        concat_list_path = output_path.with_suffix(".concat.txt")
        write_text_atomically(concat_list_path, concat_list_text(segment_paths))
        result = runner(build_concat_args(ffmpeg_path, concat_list_path, temp_output), 3600)
        output_duration = sum(durations or [])
    if result.returncode != 0:
        temp_output.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "FFmpeg не смог склеить StoryArc")
    if temp_output.exists():
        replace_atomically(temp_output, output_path)
    return max(0.1, output_duration)


def build_crossfade_args(
    ffmpeg_path: str,
    paths: list[Path],
    durations: list[float],
    output_path: Path,
    fade_seconds: float = 0.25,
    preset: RenderPresetConfig | None = None,
    use_nvenc: bool = False,
) -> list[str]:
    if len(paths) < 2 or len(durations) != len(paths):
        raise ValueError("Для плавной склейки нужны длительности всех сегментов")
    preset = preset or RENDER_PRESETS["youtube_shorts"]
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
            "h264_nvenc" if use_nvenc else "libx264",
            "-preset",
            "p5" if use_nvenc else "medium",
            "-b:v",
            preset.video_bitrate,
            "-c:a",
            "aac",
            "-b:a",
            preset.audio_bitrate,
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
    duration_seconds: float,
    runner: Callable[[list[str], int], ProcessResult],
) -> None:
    temp_output = temp_sibling(video_path).with_suffix(".mp4")
    result = runner(
        build_narration_mix_args(
            ffmpeg_path,
            video_path,
            narration_path,
            duration_seconds,
            temp_output,
        ),
        3600,
    )
    if result.returncode != 0:
        temp_output.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "FFmpeg не смог добавить озвучку")
    if temp_output.exists():
        replace_atomically(temp_output, video_path)


def build_narration_mix_args(
    ffmpeg_path: str,
    video_path: Path,
    narration_path: Path,
    duration_seconds: float,
    output_path: Path,
) -> list[str]:
    return [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(narration_path),
        "-filter_complex",
        f"[1:a]aresample=async=1:first_pts=0,atrim=duration={duration_seconds:.3f},"
        "volume=1.0[voicein];[voicein]asplit=2[voicekey][voiceout];"
        "[0:a][voicekey]sidechaincompress=threshold=0.018:ratio=8:attack=15:release=420[ducked];"
        "[ducked][voiceout]amix=inputs=2:duration=first:normalize=0:dropout_transition=0[a]",
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
        str(output_path),
    ]


def _crossfade_duration(durations: list[float], fade_seconds: float = 0.25) -> float:
    if not durations:
        return 0.0
    elapsed = durations[0]
    for index in range(1, len(durations)):
        fade = min(fade_seconds, max(0.08, durations[index - 1] / 4), max(0.08, durations[index] / 4))
        elapsed += durations[index] - fade
    return elapsed


def _narration_path(arc: StoryArc) -> Path | None:
    value = (arc.plan_json or {}).get("narration_audio_path")
    return Path(value) if isinstance(value, str) and value.strip() else None


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise ProcessCancelledError("Рендер StoryArc остановлен пользователем")


def _story_arc_render_fingerprint(
    session: Session,
    arc: StoryArc,
    settings: Settings,
    *,
    include_subtitles: bool,
    preset_name: str,
    loudnorm_two_pass: bool,
    transition_style: str,
    narration_path: Path | None,
    narration_mode: str,
    encoder_preference: bool | None,
) -> str:
    segments: list[dict] = []
    for segment in arc.segments:
        episode = session.get(Episode, segment.episode_id)
        candidate = session.get(ClipCandidate, segment.candidate_id) if segment.candidate_id else None
        if episode is None:
            raise ValueError(f"Серия сегмента {segment.id} не найдена")
        cues = (
            subtitle_cues_for_render(
                session,
                candidate,
                settings.subtitle_show_speaker_names,
                start_time=segment.start_time,
                end_time=segment.end_time,
            )
            if candidate and include_subtitles
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
        segments.append(
            {
                "id": segment.id,
                "order": segment.sort_order,
                "range": [segment.start_time, segment.end_time],
                "title": segment.title,
                "note": segment.note,
                "role": segment.role,
                "candidate_id": segment.candidate_id,
                "candidate_revision": candidate.edit_revision if candidate else segment.candidate_revision,
                "crop": {
                    "mode": candidate.crop_mode if candidate else "center-crop",
                    "offset_x": candidate.crop_offset_x if candidate else 0.0,
                    "scale": candidate.crop_scale if candidate else 1.0,
                    "keyframes": candidate.crop_keyframes_json if candidate else [],
                },
                "source": source_signature(Path(episode.file_path)),
                "episode_fingerprint": episode.fingerprint,
                "audio_stream_index": episode.selected_audio_stream_index,
                "subtitles": subtitle_text,
            }
        )
    return canonical_render_fingerprint(
        {
            "kind": "story_arc",
            "story_arc_id": arc.id,
            "arc_revision": arc.edit_revision,
            "segments": segments,
            "include_subtitles": include_subtitles,
            "subtitle_style": {
                "font": settings.subtitle_font_name,
                "size": settings.subtitle_font_size,
                "safe_zone": settings.subtitle_safe_zone,
                "speaker_names": settings.subtitle_show_speaker_names,
            },
            "preset": preset_name,
            "loudnorm_two_pass": loudnorm_two_pass,
            "transition_style": transition_style,
            "encoder_preference": encoder_preference,
            "narration": (arc.plan_json or {}).get("narration", []),
            "narration_mode": narration_mode,
            "narration_audio_sha256": small_file_sha256(narration_path),
        }
    )


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


def _normalize_narration_mode(arc: StoryArc, value: str, include_narration: bool) -> str:
    if not include_narration:
        return "none"
    mode = value if value in {"none", "narrator", "first_person"} else "first_person"
    if mode == "first_person" and not (arc.plan_json or {}).get("target_character"):
        return "narrator"
    return mode


def _safe_slug(value: str) -> str:
    slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", value)
    slug = re.sub(r"\s*-\s*", "-", slug)
    slug = re.sub(r"\s+", " ", slug).strip(" .-_")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "story-arc"


def _concat_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "'\\''")
