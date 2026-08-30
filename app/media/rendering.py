from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from app.infrastructure.atomic import replace_atomically, temp_sibling
from app.infrastructure.processes import ProcessResult, run_process


CropMode = Literal["auto-follow", "center-crop", "blurred-background"]


@dataclass(frozen=True)
class RenderedArtifacts:
    output_path: Path
    metadata_path: Path
    subtitle_path: Path | None
    cover_path: Path | None


@dataclass(frozen=True)
class RenderPresetConfig:
    name: str
    width: int = 1080
    height: int = 1920
    video_bitrate: str = "8M"
    audio_bitrate: str = "160k"


RENDER_PRESETS = {
    "youtube_shorts": RenderPresetConfig(name="youtube_shorts", video_bitrate="8M", audio_bitrate="160k"),
    "instagram_reels": RenderPresetConfig(name="instagram_reels", video_bitrate="10M", audio_bitrate="192k"),
}


def build_render_args(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    start_time: float,
    end_time: float,
    crop_mode: CropMode,
    subtitle_path: Path | None,
    use_nvenc: bool,
    preset: RenderPresetConfig | None = None,
    loudnorm_filter: str = "loudnorm=I=-16:TP=-1.5:LRA=11",
) -> list[str]:
    preset = preset or RENDER_PRESETS["youtube_shorts"]
    filters = [_crop_filter(crop_mode)]
    if subtitle_path is not None:
        filters.append(f"ass='{_escape_filter_path(subtitle_path)}'")
    encoder = "h264_nvenc" if use_nvenc else "libx264"
    duration = max(0.1, end_time - start_time)
    return [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-ss",
        f"{start_time:.3f}",
        "-i",
        str(input_path),
        "-t",
        f"{duration:.3f}",
        "-vf",
        ",".join(filters),
        "-c:v",
        encoder,
        "-b:v",
        preset.video_bitrate,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        preset.audio_bitrate,
        "-af",
        loudnorm_filter,
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def build_loudnorm_analysis_args(
    ffmpeg_path: str,
    input_path: Path,
    start_time: float,
    end_time: float,
) -> list[str]:
    duration = max(0.1, end_time - start_time)
    return [
        ffmpeg_path,
        "-hide_banner",
        "-ss",
        f"{start_time:.3f}",
        "-i",
        str(input_path),
        "-t",
        f"{duration:.3f}",
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]


def parse_loudnorm_stats(stderr: str) -> dict | None:
    start = stderr.find("{")
    end = stderr.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return None


def loudnorm_second_pass_filter(stats: dict | None) -> str:
    if not stats:
        return "loudnorm=I=-16:TP=-1.5:LRA=11"
    required = ["input_i", "input_tp", "input_lra", "input_thresh", "target_offset"]
    if not all(key in stats for key in required):
        return "loudnorm=I=-16:TP=-1.5:LRA=11"
    return (
        "loudnorm=I=-16:TP=-1.5:LRA=11:"
        f"measured_I={stats['input_i']}:"
        f"measured_TP={stats['input_tp']}:"
        f"measured_LRA={stats['input_lra']}:"
        f"measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}:linear=true:print_format=summary"
    )


def build_cover_args(ffmpeg_path: str, input_path: Path, output_path: Path, at_seconds: float) -> list[str]:
    return [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-ss",
        f"{at_seconds:.3f}",
        "-i",
        str(input_path),
        "-frames:v",
        "1",
        "-vf",
        _crop_filter("blurred-background"),
        str(output_path),
    ]


def render_clip(
    ffmpeg_path: str,
    input_path: Path,
    output_dir: Path,
    slug: str,
    start_time: float,
    end_time: float,
    crop_mode: CropMode,
    subtitle_text: str | None,
    metadata: dict,
    use_nvenc: bool = False,
    preset_name: str = "youtube_shorts",
    loudnorm_two_pass: bool = False,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> RenderedArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    subtitle_path = output_dir / f"{slug}.ass" if subtitle_text else None
    if subtitle_path is not None:
        subtitle_path.write_text(subtitle_text, encoding="utf-8")
    output_path = output_dir / f"{slug}.mp4"
    temp_output = temp_sibling(output_path).with_suffix(".mp4")
    preset = RENDER_PRESETS.get(preset_name, RENDER_PRESETS["youtube_shorts"])
    loudnorm_filter = "loudnorm=I=-16:TP=-1.5:LRA=11"
    if loudnorm_two_pass:
        analysis = runner(build_loudnorm_analysis_args(ffmpeg_path, input_path, start_time, end_time), 1800)
        if analysis.returncode == 0:
            loudnorm_filter = loudnorm_second_pass_filter(parse_loudnorm_stats(analysis.stderr))
    def run_video_render(enable_nvenc: bool) -> ProcessResult:
        return runner(
            build_render_args(
                ffmpeg_path,
                input_path,
                temp_output,
                start_time,
                end_time,
                crop_mode,
                subtitle_path,
                enable_nvenc,
                preset=preset,
                loudnorm_filter=loudnorm_filter,
            ),
            3600,
        )

    result = run_video_render(use_nvenc)
    if result.returncode != 0 and use_nvenc:
        temp_output.unlink(missing_ok=True)
        result = run_video_render(False)
    if result.returncode != 0:
        temp_output.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "FFmpeg не смог отрендерить клип")
    if temp_output.exists():
        replace_atomically(temp_output, output_path)
    cover_path = output_dir / f"{slug}.jpg"
    cover_result = runner(build_cover_args(ffmpeg_path, input_path, cover_path, start_time + 1.0), 300)
    if cover_result.returncode != 0:
        cover_path = None
    metadata_path = output_dir / f"{slug}.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return RenderedArtifacts(output_path, metadata_path, subtitle_path, cover_path)


def _crop_filter(crop_mode: CropMode) -> str:
    if crop_mode == "center-crop" or crop_mode == "auto-follow":
        return "scale=-2:1920,crop=1080:1920"
    return (
        "split=2[base][fg];"
        "[base]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=28[bg];"
        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fit];"
        "[bg][fit]overlay=(W-w)/2:(H-h)/2"
    )


def _escape_filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:")


def detect_nvenc(ffmpeg_path: str, runner: Callable[[list[str], int], ProcessResult] = run_process) -> bool:
    try:
        result = runner([ffmpeg_path, "-hide_banner", "-encoders"], 30)
    except Exception:
        return False
    return result.returncode == 0 and "h264_nvenc" in (result.stdout + result.stderr)
