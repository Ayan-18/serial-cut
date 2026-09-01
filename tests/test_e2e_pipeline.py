from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from app.application.importer import import_season
from app.application.review import review_candidate
from app.application.stage2 import run_stage2_media_analysis
from app.application.stage3 import run_stage3_candidate_analysis
from app.application.stage4 import render_candidate
from app.infrastructure.config import Settings
from app.infrastructure.processes import run_process
from app.media.scenes import StubSceneDetector
from app.media.transcription import StubTranscriber
from app.models.entities import ClipCandidate, Episode, Export


def _make_sample(ffmpeg: str, path: Path) -> None:
    result = run_process(
        [
            ffmpeg, "-hide_banner", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000",
            "-t", "6", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ],
        60,
    )
    assert result.returncode == 0, result.stderr


def test_import_probe_stage2_stage3_render_pipeline(session, tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/ffprobe are not installed")

    season_dir = tmp_path / "Сезон 1"
    season_dir.mkdir()
    _make_sample(ffmpeg, season_dir / "episode-01.mp4")

    settings = Settings(
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        cache_dir=tmp_path / "cache",
        output_dir=tmp_path / "out",
        asr_adapter="stub",
        llm_adapter="stub",
        min_clip_seconds=2,
        max_clip_seconds=5,
        export_filename_template="clip{candidate}",
    )

    # Stage 1: import + fingerprint/dedupe.
    first = import_season(session, season_dir)
    session.commit()
    assert first.created == 1
    episode_id = first.episode_ids[0]
    assert import_season(session, season_dir).skipped_duplicates == 1

    # Stage 2: real ffmpeg probe/proxy/audio, stub ASR + scene detection.
    stage2 = run_stage2_media_analysis(
        session,
        episode_id,
        settings,
        transcriber=StubTranscriber(),
        scene_detector=StubSceneDetector(),
    )
    session.commit()
    assert stage2.transcript_segments >= 1
    assert stage2.scenes >= 1
    episode = session.get(Episode, episode_id)
    assert episode.duration_seconds and episode.duration_seconds > 0
    assert Path(episode.proxy_path).exists()
    assert Path(episode.audio_path).exists()

    # Stage 3: stub analyzer -> validated candidates.
    stage3 = run_stage3_candidate_analysis(session, episode_id, settings)
    session.commit()
    assert stage3.candidates >= 1
    candidate = session.scalars(
        select(ClipCandidate).where(ClipCandidate.episode_id == episode_id)
    ).first()
    assert candidate is not None

    # Stage 4: review + real vertical render.
    review_candidate(session, candidate.id, "approve")
    session.commit()
    result = render_candidate(session, candidate.id, settings, include_subtitles=True, use_nvenc=False)
    session.commit()

    export = session.get(Export, result.export_id)
    assert export is not None and export.status == "completed"
    assert Path(export.output_path).exists()

    probe = run_process(
        [ffprobe, "-v", "error", "-show_streams", "-of", "json", export.output_path],
        30,
    )
    assert probe.returncode == 0, probe.stderr
    assert '"codec_type": "video"' in probe.stdout
