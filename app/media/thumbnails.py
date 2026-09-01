from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.infrastructure.processes import ProcessResult, run_process

logger = logging.getLogger(__name__)

MIN_KEYFRAMES = 3
MAX_KEYFRAMES = 16


@dataclass(frozen=True)
class Keyframe:
    index: int
    time: float
    path: Path


def build_keyframe_args(
    ffmpeg_path: str,
    source: Path,
    output_pattern: Path,
    start_time: float,
    end_time: float,
    count: int,
    height: int = 200,
) -> list[str]:
    duration = max(0.1, end_time - start_time)
    return [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-ss",
        f"{max(0.0, start_time):.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.3f}",
        "-vf",
        f"fps={count}/{duration:.3f},scale=-2:{height}",
        "-frames:v",
        str(count),
        "-f",
        "image2",
        str(output_pattern),
    ]


def extract_keyframes(
    ffmpeg_path: str,
    source: Path,
    output_dir: Path,
    start_time: float,
    end_time: float,
    count: int,
    *,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> list[Keyframe]:
    """Evenly-spaced JPEG thumbnails across a candidate range, cached by directory.

    ``output_dir`` is expected to already encode the candidate id and its edit
    revision, so a boundary change lands in a fresh directory.
    """
    count = max(MIN_KEYFRAMES, min(MAX_KEYFRAMES, count))
    duration = max(0.1, end_time - start_time)
    existing = sorted(output_dir.glob("frame-*.jpg"))
    if len(existing) < count:
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        result = runner(
            build_keyframe_args(
                ffmpeg_path,
                source,
                output_dir / "frame-%02d.jpg",
                start_time,
                end_time,
                count,
            ),
            300,
        )
        existing = sorted(output_dir.glob("frame-*.jpg"))
        if result.returncode != 0 and not existing:
            logger.warning("Keyframe extraction failed: returncode=%s source=%s", result.returncode, source)
            raise RuntimeError(result.stderr.strip() or "FFmpeg не смог собрать раскадровку")
    frames: list[Keyframe] = []
    for position, path in enumerate(existing[:count]):
        timestamp = start_time + duration * (position + 0.5) / count
        frames.append(Keyframe(index=position, time=round(timestamp, 3), path=path))
    return frames
