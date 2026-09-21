"""FFmpeg argument builders and process invocations for StoryArc rendering:
concatenating segments (straight cut or crossfade) and mixing in narration.
Pulled out of story_arc_render.py because none of it touches the per-segment
`render_clip`/`detect_nvenc` calls that tests monkeypatch on that module."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.infrastructure.atomic import replace_atomically, temp_sibling, write_text_atomically
from app.infrastructure.processes import ProcessResult
from app.media.rendering import RENDER_PRESETS, RenderPresetConfig


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
    # xfade negotiates its own pixel format and can land on 4:4:4, which browsers
    # and most players refuse to decode — the export then shows a black screen.
    # Force 4:2:0 back on the way out.
    filters.append(f"[{video_label}]format=yuv420p[vout]")
    args.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            f"[{audio_label}]",
            "-c:v",
            "h264_nvenc" if use_nvenc else "libx264",
            "-preset",
            "p5" if use_nvenc else "medium",
            "-pix_fmt",
            "yuv420p",
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


def _concat_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "'\\''")
