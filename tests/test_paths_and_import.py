from __future__ import annotations

from pathlib import Path

from app.application.importer import import_season
from app.domain.paths import is_supported_video, normalize_local_path


def test_windows_like_paths_with_spaces_and_cyrillic_are_supported(tmp_path: Path):
    season = tmp_path / "Сериал с пробелами" / "Сезон 1"
    season.mkdir(parents=True)
    media = season / "Серия 01.mkv"
    media.write_bytes(b"synthetic-video")

    normalized = normalize_local_path(season)

    assert "Сериал с пробелами" in str(normalized)
    assert is_supported_video(media)


def test_import_season_deduplicates_by_fingerprint(session, tmp_path: Path):
    season = tmp_path / "Сезон"
    season.mkdir()
    media = season / "episode 01.mkv"
    media.write_bytes(b"same-content")

    first = import_season(session, season)
    session.commit()
    second = import_season(session, season)
    session.commit()

    assert first.created == 1
    assert second.created == 0
    assert second.skipped_duplicates == 1
    assert first.episode_ids == second.episode_ids

