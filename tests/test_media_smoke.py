from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from app.application.narration import build_narration_timeline_args
from app.application.story_arc_render import render_story_arc
from app.application.story_arc_render import build_narration_mix_args
from app.infrastructure.config import Settings
from app.infrastructure.processes import run_process
from app.media.rendering import render_clip
from app.models.entities import ClipCandidate, Episode, Season, StoryArc, StoryArcSegment


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


def test_generated_story_arc_render_produces_playable_multi_source_mp4(session, tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/ffprobe are not installed")
    sources: list[Path] = []
    for index, color in enumerate(("red", "green"), start=1):
        source = tmp_path / f"source-{index}.mp4"
        generated = run_process(
            [
                ffmpeg, "-hide_banner", "-y",
                "-f", "lavfi", "-i", f"color=c={color}:size=640x360:rate=24",
                "-f", "lavfi", "-i", f"sine=frequency={330 + index * 110}:sample_rate=48000",
                "-t", "2", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
            ],
            60,
        )
        assert generated.returncode == 0, generated.stderr
        sources.append(source)

    season = Season(title="Smoke Season", root_path=str(tmp_path))
    session.add(season)
    session.flush()
    candidates: list[ClipCandidate] = []
    for index, source in enumerate(sources, start=1):
        episode = Episode(
            season_id=season.id,
            file_path=str(source),
            file_name=source.name,
            fingerprint=f"story-smoke-{index}",
            size_bytes=source.stat().st_size,
            modified_ns=source.stat().st_mtime_ns,
            duration_seconds=2.0,
            width=640,
            height=360,
            fps=24.0,
            selected_audio_stream_index=1,
        )
        session.add(episode)
        session.flush()
        candidate = ClipCandidate(
            episode_id=episode.id,
            start_time=0.2,
            end_time=1.7,
            title=f"Part {index}",
            description="Generated StoryArc smoke segment.",
            moment_type="smoke",
            score=90,
            scores_json={},
            rationale="Synthetic media check",
            problems_json=[],
        )
        session.add(candidate)
        candidates.append(candidate)
    session.flush()
    arc = StoryArc(
        season_id=season.id,
        title="Generated StoryArc Smoke",
        prompt="",
        plan_json={"narration": []},
        total_duration_seconds=3.0,
    )
    session.add(arc)
    session.flush()
    for index, candidate in enumerate(candidates, start=1):
        session.add(
            StoryArcSegment(
                story_arc_id=arc.id,
                episode_id=candidate.episode_id,
                candidate_id=candidate.id,
                sort_order=index,
                start_time=candidate.start_time,
                end_time=candidate.end_time,
                title=candidate.title,
                note="",
            )
        )
    session.flush()

    result = render_story_arc(
        session,
        arc.id,
        Settings(ffmpeg_path=ffmpeg, ffprobe_path=ffprobe, cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"),
        include_subtitles=False,
        include_narration=False,
        transition_style="fade",
        preset_name="preview",
        use_nvenc=False,
    )

    probe = run_process([ffprobe, "-v", "error", "-show_streams", "-of", "json", result.output_path], 30)
    assert probe.returncode == 0, probe.stderr
    streams = json.loads(probe.stdout)["streams"]
    assert result.segment_count == 2
    assert Path(result.output_path).exists()
    assert {item["codec_type"] for item in streams} == {"video", "audio"}
