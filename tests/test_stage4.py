from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.application.importer import import_season
from app.application.review import review_candidate
from app.application.stage4 import render_candidate
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessResult
from app.media.rendering import (
    build_loudnorm_analysis_args,
    build_render_args,
    detect_nvenc,
    loudnorm_second_pass_filter,
    parse_loudnorm_stats,
    render_clip,
)
from app.media.subtitles import SubtitleCue, cues_for_words, render_ass, render_srt, wrap_russian_subtitle
from app.models.entities import ClipCandidate, Export, TranscriptSegment, WordTimestamp


def test_russian_subtitles_wrap_to_two_lines_and_render_formats():
    lines = wrap_russian_subtitle("Это длинная русская фраза которая должна стать читаемой на телефоне", max_chars=22)

    assert all(line.count("\\N") <= 1 for line in lines)
    assert "00:00:01,000" in render_srt([SubtitleCue(1, 2.5, lines[0])])
    ass = render_ass([SubtitleCue(1, 2.5, lines[0])], font_size=48)
    assert "Dialogue:" in ass
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "Style: Default,Segoe UI,48" in ass


def test_word_subtitles_show_every_word_once_with_sequential_timing():
    words = [
        WordTimestamp(segment_id=1, start_time=index * 0.4, end_time=index * 0.4 + 0.3, word=word)
        for index, word in enumerate(
            "Все распознанные слова должны последовательно появиться в готовом вертикальном видео".split()
        )
    ]

    cues = cues_for_words(words, start_time=0, end_time=10, max_chars_per_line=18, max_seconds=2)
    rendered_words = " ".join(cue.text.replace("\\N", " ") for cue in cues).split()

    assert rendered_words == [word.word for word in words]
    assert all(left.end_time <= right.start_time + 0.2 for left, right in zip(cues, cues[1:], strict=False))


def test_render_command_builds_vertical_h264_aac_clip_without_shell():
    args = build_render_args(
        "ffmpeg",
        Path(r"D:\Сериал\episode 1.mkv"),
        Path(r"C:\out\clip.mp4"),
        1.2,
        46.2,
        "blurred-background",
        Path(r"C:\out\clip.ass"),
        use_nvenc=True,
    )

    assert args[0] == "ffmpeg"
    assert "h264_nvenc" in args
    assert "8M" in args
    assert "aac" in args
    assert "-vf" in args
    assert args[-1] == r"C:\out\clip.mp4"


def test_render_clip_writes_metadata_and_uses_temp_output(tmp_path: Path):
    def fake_runner(args: list[str], timeout: int) -> ProcessResult:
        output = Path(args[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"rendered")
        return ProcessResult(args, 0, "", "")

    artifacts = render_clip(
        "ffmpeg",
        tmp_path / "source.mp4",
        tmp_path / "out",
        "clip",
        0,
        35,
        "center-crop",
        "ASS",
        {"title": "Тест"},
        runner=fake_runner,
    )

    assert artifacts.output_path.exists()
    assert artifacts.metadata_path.read_text(encoding="utf-8")
    assert artifacts.subtitle_path is not None and artifacts.subtitle_path.exists()


def test_render_clip_falls_back_to_cpu_when_nvenc_fails(tmp_path: Path):
    calls: list[list[str]] = []

    def fake_runner(args: list[str], timeout: int) -> ProcessResult:
        calls.append(args)
        if "h264_nvenc" in args:
            return ProcessResult(args, 1, "", "NVENC driver is too old")
        output = Path(args[-1])
        if output.suffix == ".mp4":
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"rendered")
        return ProcessResult(args, 0, "", "")

    artifacts = render_clip(
        "ffmpeg",
        tmp_path / "source.mp4",
        tmp_path / "out",
        "clip",
        0,
        35,
        "center-crop",
        None,
        {"title": "Тест"},
        use_nvenc=True,
        runner=fake_runner,
    )

    assert artifacts.output_path.exists()
    assert "h264_nvenc" in calls[0]
    assert "libx264" in calls[1]


def test_nvenc_detection_and_loudnorm_second_pass_helpers(tmp_path: Path):
    def fake_runner(args: list[str], timeout: int) -> ProcessResult:
        return ProcessResult(args, 0, " V..... h264_nvenc NVIDIA NVENC H.264 encoder", "")

    assert detect_nvenc("ffmpeg", runner=fake_runner)
    analysis_args = build_loudnorm_analysis_args("ffmpeg", tmp_path / "source.mp4", 2.0, 12.0)
    assert "print_format=json" in " ".join(analysis_args)
    stats = parse_loudnorm_stats(
        'noise\n{"input_i":"-20.0","input_tp":"-2.0","input_lra":"5.0","input_thresh":"-30.0","target_offset":"1.0"}'
    )
    assert stats is not None
    assert "measured_I=-20.0" in loudnorm_second_pass_filter(stats)


def test_review_and_render_are_idempotent(session, tmp_path: Path, monkeypatch):
    season = tmp_path / "Сезон"
    season.mkdir()
    source = season / "episode.mkv"
    source.write_bytes(b"video")
    imported = import_season(session, season)
    episode_id = imported.episode_ids[0]
    session.add(TranscriptSegment(episode_id=episode_id, start_time=0, end_time=40, text="Русская реплика"))
    candidate = ClipCandidate(
        episode_id=episode_id,
        start_time=0,
        end_time=35,
        title="Тест",
        description="Описание",
        moment_type="другое",
        score=90,
        scores_json={},
        rationale="Понятен",
        problems_json=[],
    )
    session.add(candidate)
    session.flush()

    first_review = review_candidate(session, candidate.id, "approve", crop_mode="center-crop")
    second_review = review_candidate(session, candidate.id, "approve", crop_mode="center-crop")
    assert first_review.decision_id == second_review.decision_id

    render_calls = 0

    def fake_render_clip(*args, **kwargs):
        nonlocal render_calls
        render_calls += 1
        out = tmp_path / "out" / "clip.mp4"
        meta = tmp_path / "out" / "clip.json"
        sub = tmp_path / "out" / "clip.ass"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        meta.write_text("{}", encoding="utf-8")
        sub.write_text("ass", encoding="utf-8")
        return type("Artifacts", (), {"output_path": out, "metadata_path": meta, "subtitle_path": sub, "cover_path": None})()

    monkeypatch.setattr("app.application.stage4.render_clip", fake_render_clip)
    first_render = render_candidate(session, candidate.id, Settings(output_dir=tmp_path / "out"))
    second_render = render_candidate(session, candidate.id, Settings(output_dir=tmp_path / "out"))
    forced_render = render_candidate(
        session,
        candidate.id,
        Settings(output_dir=tmp_path / "out"),
        force_rerender=True,
    )

    assert first_render.export_id == second_render.export_id
    assert first_render.export_id == forced_render.export_id
    assert render_calls == 2
    assert len(session.scalars(select(Export)).all()) == 1
