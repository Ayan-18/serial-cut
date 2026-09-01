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


def test_import_season_reports_progress_and_survives_a_locked_file(session, tmp_path, monkeypatch):
    season = tmp_path / "Сезон"
    season.mkdir()
    (season / "episode 01.mkv").write_bytes(b"one")
    (season / "episode 02.mkv").write_bytes(b"two")

    from app.application import importer

    real_fingerprint = importer.fingerprint_file

    def flaky_fingerprint(path):
        if path.name == "episode 01.mkv":
            raise PermissionError("used by another process")
        return real_fingerprint(path)

    monkeypatch.setattr(importer, "fingerprint_file", flaky_fingerprint)

    seen: list[tuple[int, int, str]] = []
    result = import_season(session, season, progress_callback=lambda *args: seen.append(args))
    session.commit()

    assert result.scanned == 2
    assert result.created == 1
    assert [error.file_name for error in result.errors] == ["episode 01.mkv"]
    assert seen[-1][:2] == (2, 2)

