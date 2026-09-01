from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable

from app.domain.enums import EpisodeStage, TrackKind
from app.infrastructure.processes import ProcessResult, run_process
from app.models.entities import Episode, MediaTrack


@dataclass(frozen=True)
class ProbeSummary:
    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: float | None
    raw: dict


def build_ffprobe_args(ffprobe_path: str, media_path: Path) -> list[str]:
    return [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(media_path),
    ]


def probe_media(
    ffprobe_path: str,
    media_path: Path,
    timeout_seconds: int = 60,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> ProbeSummary:
    result = runner(build_ffprobe_args(ffprobe_path, media_path), timeout_seconds)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "ffprobe завершился с ошибкой"
        raise RuntimeError(detail)
    raw = json.loads(result.stdout)
    return summarize_probe(raw)


def summarize_probe(raw: dict) -> ProbeSummary:
    streams = raw.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    format_info = raw.get("format", {})
    duration = _float_or_none(format_info.get("duration"))
    width = int(video_stream["width"]) if video_stream and video_stream.get("width") else None
    height = int(video_stream["height"]) if video_stream and video_stream.get("height") else None
    fps = _fps_or_none(video_stream.get("avg_frame_rate")) if video_stream else None
    return ProbeSummary(duration_seconds=duration, width=width, height=height, fps=fps, raw=raw)


def apply_probe_to_episode(episode: Episode, summary: ProbeSummary) -> None:
    episode.duration_seconds = summary.duration_seconds
    episode.width = summary.width
    episode.height = summary.height
    episode.fps = summary.fps
    episode.probe_json = summary.raw
    episode.stage = EpisodeStage.PROBED.value
    episode.tracks.clear()
    for stream in summary.raw.get("streams", []):
        tags = stream.get("tags") or {}
        episode.tracks.append(
            MediaTrack(
                stream_index=int(stream.get("index", 0)),
                kind=_track_kind(stream.get("codec_type")).value,
                codec=stream.get("codec_name"),
                language=tags.get("language"),
                title=tags.get("title"),
                raw=stream,
            )
        )


def _track_kind(codec_type: str | None) -> TrackKind:
    match codec_type:
        case "video":
            return TrackKind.VIDEO
        case "audio":
            return TrackKind.AUDIO
        case "subtitle":
            return TrackKind.SUBTITLE
        case _:
            return TrackKind.OTHER


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _fps_or_none(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    return float(Fraction(value))

