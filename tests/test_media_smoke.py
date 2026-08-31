from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

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
