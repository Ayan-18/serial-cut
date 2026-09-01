from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from app.application.narration import build_narration_timeline_args
from app.application.story_arc_render import build_narration_mix_args
from app.infrastructure.processes import run_process
from app.media.rendering import render_clip


def test_generated_media_can_render_to_vertical_h264_aac(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/ffprobe are not installed")
    source = tmp_path / "source.mp4"
    generated = run_process(
        [
            ffmpeg, "-hide_banner", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "3", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
        ],
        60,
    )
    assert generated.returncode == 0, generated.stderr

    artifacts = render_clip(
        ffmpeg,
        source,
        tmp_path / "rendered",
        "smoke",
        0.5,
        2.5,
        "center-crop",
        None,
        {"purpose": "generated media smoke test"},
        preset_name="preview",
        runner=run_process,
    )
    probe = run_process(
        [ffprobe, "-v", "error", "-show_streams", "-of", "json", str(artifacts.output_path)],
        30,
    )
    assert probe.returncode == 0, probe.stderr
    streams = json.loads(probe.stdout)["streams"]
    video = next(item for item in streams if item["codec_type"] == "video")
    audio = next(item for item in streams if item["codec_type"] == "audio")
    assert (video["codec_name"], video["width"], video["height"]) == ("h264", 540, 960)
    assert audio["codec_name"] == "aac"
    assert artifacts.cover_path is not None and artifacts.cover_path.exists()


def test_narration_timeline_and_ducking_filters_run_in_ffmpeg(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/ffprobe are not installed")
    video = tmp_path / "base.mp4"
    generated = run_process(
        [
            ffmpeg, "-hide_banner", "-y",
            "-f", "lavfi", "-i", "color=c=blue:size=320x240:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000",
            "-t", "3", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video),
        ],
        60,
    )
    assert generated.returncode == 0, generated.stderr

    parts: list[Path] = []
    for index, frequency in enumerate((660, 880), start=1):
        part = tmp_path / f"voice-{index}.wav"
        result = run_process(
            [
                ffmpeg, "-hide_banner", "-y", "-f", "lavfi", "-i",
                f"sine=frequency={frequency}:sample_rate=48000:duration=0.4",
                "-c:a", "pcm_s16le", str(part),
            ],
            30,
        )
        assert result.returncode == 0, result.stderr
        parts.append(part)

    timeline = tmp_path / "timeline.wav"
    timeline_result = run_process(
        build_narration_timeline_args(
            ffmpeg,
            parts,
            [{"start_time": 0.2}, {"start_time": 1.5}],
            [0.4, 0.4],
            3.0,
            timeline,
        ),
        30,
    )
    assert timeline_result.returncode == 0, timeline_result.stderr

    mixed = tmp_path / "mixed.mp4"
    mix_result = run_process(build_narration_mix_args(ffmpeg, video, timeline, 3.0, mixed), 30)
    assert mix_result.returncode == 0, mix_result.stderr
    probe = run_process([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(mixed)], 30)
    assert probe.returncode == 0, probe.stderr
    streams = json.loads(probe.stdout)["streams"]
    assert {item["codec_type"] for item in streams} == {"video", "audio"}
