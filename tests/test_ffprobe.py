from __future__ import annotations

from pathlib import Path

from app.media.ffmpeg import build_extract_audio_args, build_proxy_args
from app.media.ffprobe import build_ffprobe_args, summarize_probe


def test_ffprobe_command_uses_argument_list_for_unsafe_paths():
    path = Path(r"D:\Видео тест\серия 01; rm nope.mkv")

    args = build_ffprobe_args("ffprobe", path)

    assert args[-1] == str(path)
    assert "; rm nope" in args[-1]
    assert all(isinstance(item, str) for item in args)


def test_summarize_probe_extracts_video_metadata():
    summary = summarize_probe(
        {
            "format": {"duration": "2700.500"},
            "streams": [
                {"index": 0, "codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "25/1"},
                {"index": 1, "codec_type": "audio", "codec_name": "aac", "tags": {"language": "rus"}},
            ],
        }
    )

    assert summary.duration_seconds == 2700.5
    assert summary.width == 1920
    assert summary.height == 1080
    assert summary.fps == 25.0


def test_extract_audio_command_maps_selected_stream_and_normalizes_for_whisper():
    args = build_extract_audio_args(
        "ffmpeg",
        Path(r"D:\Видео тест\серия 01.mkv"),
        Path(r"C:\cache\audio.wav"),
        audio_stream_index=2,
    )

    assert args[:4] == ["ffmpeg", "-hide_banner", "-y", "-i"]
    assert ["-map", "0:2"] == args[5:7]
    assert "-ac" in args
    assert "1" in args
    assert "-ar" in args
    assert "16000" in args
    assert args[-1] == r"C:\cache\audio.wav"


def test_proxy_command_uses_video_only_scaled_h264_output():
    args = build_proxy_args(
        "ffmpeg",
        Path(r"D:\Видео тест\серия 01.mkv"),
        Path(r"C:\cache\proxy.mp4"),
        width=640,
        crf=28,
    )

    assert "-map" in args
    assert "0:v:0" in args
    assert "-an" in args
    assert "scale=640:-2" in args
    assert "libx264" in args
    assert args[-1] == r"C:\cache\proxy.mp4"

