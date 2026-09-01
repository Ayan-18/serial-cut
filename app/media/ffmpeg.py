from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.infrastructure.atomic import replace_atomically, temp_sibling
from app.infrastructure.processes import ProcessResult, run_process


def build_extract_audio_args(
    ffmpeg_path: str,
    media_path: Path,
    output_path: Path,
    audio_stream_index: int | None,
) -> list[str]:
    args = [ffmpeg_path, "-hide_banner", "-y", "-i", str(media_path)]
    if audio_stream_index is not None:
        args.extend(["-map", f"0:{audio_stream_index}"])
    else:
        args.extend(["-map", "0:a:0"])
    args.extend(["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output_path)])
    return args


def build_proxy_args(
    ffmpeg_path: str,
    media_path: Path,
    output_path: Path,
    width: int,
    crf: int,
    audio_stream_index: int | None = None,
) -> list[str]:
    args = [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-i",
        str(media_path),
        "-map",
        "0:v:0",
        "-map",
        f"0:{audio_stream_index}" if audio_stream_index is not None else "0:a:0?",
        "-vf",
        f"scale={width}:-2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(crf),
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    return args


def extract_audio(
    ffmpeg_path: str,
    media_path: Path,
    output_path: Path,
    audio_stream_index: int | None,
    timeout_seconds: int = 1800,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> Path:
    temp_path = temp_sibling(output_path).with_suffix(".wav")
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    result = runner(
        build_extract_audio_args(ffmpeg_path, media_path, temp_path, audio_stream_index),
        timeout_seconds,
    )
    if result.returncode != 0:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "FFmpeg не смог извлечь аудио")
    replace_atomically(temp_path, output_path)
    return output_path


def create_proxy(
    ffmpeg_path: str,
    media_path: Path,
    output_path: Path,
    width: int,
    crf: int,
    audio_stream_index: int | None = None,
    timeout_seconds: int = 1800,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> Path:
    temp_path = temp_sibling(output_path).with_suffix(".mp4")
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    result = runner(
        build_proxy_args(ffmpeg_path, media_path, temp_path, width, crf, audio_stream_index),
        timeout_seconds,
    )
    if result.returncode != 0:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "FFmpeg не смог создать proxy")
    replace_atomically(temp_path, output_path)
    return output_path
