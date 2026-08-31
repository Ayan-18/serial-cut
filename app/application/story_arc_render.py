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
from app.infrastructure.atomic import replace_atomically, temp_sibling
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessResult, run_process
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
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> StoryArcRenderResult:
    arc = _load_arc(session, story_arc_id)
    existing = session.scalar(
        select(StoryArcExport)
        .where(StoryArcExport.story_arc_id == story_arc_id)
        .order_by(StoryArcExport.created_at.desc())
    )
    if existing is not None and not force_rerender:
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
    segment_metadata: list[dict] = []
    first_cover: Path | None = None

    for segment in arc.segments:
        candidate = session.get(ClipCandidate, segment.candidate_id) if segment.candidate_id else None
        episode = session.get(Episode, segment.episode_id)
        if episode is None:
            raise ValueError(f"Серия сегмента {segment.id} не найдена")
        crop_mode = candidate.crop_mode if candidate else "blurred-background"
        crop_offset_x = candidate.crop_offset_x if candidate else 0.0
        crop_scale = candidate.crop_scale if candidate else 1.0
        crop_keyframes = candidate.crop_keyframes_json if candidate else []
        cues = subtitle_cues_for_render(session, candidate, settings.subtitle_show_speaker_names) if candidate else []
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

    output_path = output_dir / f"{output_slug}.mp4"
    _concat_segments(settings.ffmpeg_path, segment_paths, output_path, runner)
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
        "segments": segment_metadata,
        "narration": (arc.plan_json or {}).get("narration", []),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    cover_path = output_dir / f"{output_slug}.jpg"
    if first_cover is not None and first_cover.exists():
        shutil.copyfile(first_cover, cover_path)
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
    arc.status = "rendered"
    if existing is None:
        session.add(export)
    session.flush()
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
) -> None:
    if not segment_paths:
        raise ValueError("Нет сегментов для склейки")
    concat_list_path = output_path.with_suffix(".concat.txt")
    concat_list_path.write_text(concat_list_text(segment_paths), encoding="utf-8")
    temp_output = temp_sibling(output_path).with_suffix(".mp4")
    result = runner(build_concat_args(ffmpeg_path, concat_list_path, temp_output), 3600)
    if result.returncode != 0:
        temp_output.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "FFmpeg не смог склеить StoryArc")
    if temp_output.exists():
        replace_atomically(temp_output, output_path)


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
