from __future__ import annotations

from pathlib import Path

from app.infrastructure.atomic import temp_sibling, write_text_atomically


def test_temp_sibling_is_short_and_independent_of_a_long_final_name(tmp_path: Path):
    long_name = "a" * 180 + "_clip-13_score-82-v001-3a7fb55d-5a0ed5f0.ass"
    final = tmp_path / long_name

    temp = temp_sibling(final)

    assert temp.parent == final.parent
    assert temp.name.startswith(".") and temp.name.endswith(".tmp")
    # The long final name must not leak into the temp name (that used to blow
    # past the Windows 260-char path limit).
    assert long_name not in temp.name
    assert len(temp.name) < 25


def test_temp_sibling_keeps_a_requested_extension(tmp_path: Path):
    temp = temp_sibling(tmp_path / "clip.mp4").with_suffix(".mp4")
    assert temp.suffix == ".mp4"
    assert temp.parent == tmp_path


def test_write_text_atomically_replaces_and_cleans_up(tmp_path: Path):
    target = tmp_path / "нарезка" / "subs.ass"

    write_text_atomically(target, "[Script Info]\n")

    assert target.read_text(encoding="utf-8") == "[Script Info]\n"
    assert list(tmp_path.rglob(".*.tmp")) == []
