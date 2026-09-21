"""Non-ffmpeg helpers for StoryArc rendering: the render fingerprint (decides
whether a cached export can be reused), path/slug naming, narration-mode
normalization, and loading the arc. Split out of story_arc_render.py so that
file is left with just the render orchestration and the ffmpeg concat/mix
helpers touch."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

from app.application.candidate_editor import subtitle_cues_for_render
from app.application.render_fingerprint import (
    canonical_render_fingerprint,
    small_file_sha256,
    source_signature,
)
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessCancelledError
from app.media.subtitles import render_ass
from app.models.entities import ClipCandidate, Episode, StoryArc


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
                animate=settings.subtitle_animate,
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
                "animate": settings.subtitle_animate,
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
