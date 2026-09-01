from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.application.candidate_keyframes import build_candidate_keyframes, candidate_keyframe_file
from app.infrastructure.config import Settings
from app.infrastructure.processes import run_process
from app.media.thumbnails import build_keyframe_args
from app.models.entities import ClipCandidate, Episode, Season


def test_build_keyframe_args_uses_fractional_fps_across_the_range():
    args = build_keyframe_args("ffmpeg", Path("in.mp4"), Path("out-%02d.jpg"), 10.0, 18.0, 4)
    vf = args[args.index("-vf") + 1]
    assert "fps=4/8.000" in vf
    assert args[args.index("-frames:v") + 1] == "4"


def test_extract_and_serve_candidate_keyframes(session, tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is not installed")
    source = tmp_path / "proxy.mp4"
    generated = run_process(
        [
            ffmpeg, "-hide_banner", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24",
            "-t", "6", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", str(source),
        ],
        60,
    )
    assert generated.returncode == 0, generated.stderr

    season = Season(title="S", root_path=str(tmp_path))
    session.add(season)
    session.flush()
    episode = Episode(
        season_id=season.id,
        file_path=str(source),
        file_name="proxy.mp4",
        fingerprint="fp-keyframes",
        size_bytes=source.stat().st_size,
        modified_ns=source.stat().st_mtime_ns,
        proxy_path=str(source),
        duration_seconds=6.0,
    )
    session.add(episode)
    session.flush()
    candidate = ClipCandidate(
        episode_id=episode.id,
        start_time=1.0,
        end_time=5.0,
        title="Момент",
        description="d",
        moment_type="другое",
        score=80,
        scores_json={},
        rationale="r",
        problems_json=[],
    )
    session.add(candidate)
    session.flush()

    settings = Settings(ffmpeg_path=ffmpeg, cache_dir=tmp_path / "cache", output_dir=tmp_path / "out")

    strip = build_candidate_keyframes(session, candidate.id, settings, count=6)
    assert len(strip.frames) == 6
    assert strip.frames[0].time >= 1.0 and strip.frames[-1].time <= 5.0
    assert strip.frames[0].url == f"/api/candidates/{candidate.id}/keyframes/0"

    frame_path = candidate_keyframe_file(session, candidate.id, settings, 0)
    assert frame_path.is_file()

    # Second call reuses the cached directory (no ffmpeg rerun needed).
    again = build_candidate_keyframes(session, candidate.id, settings, count=6)
    assert [f.time for f in again.frames] == [f.time for f in strip.frames]
