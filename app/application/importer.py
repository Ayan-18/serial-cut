from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import EpisodeStage
from app.infrastructure.filesystem import discover_video_files
from app.infrastructure.fingerprint import fingerprint_file
from app.models.entities import Episode, Season

logger = logging.getLogger(__name__)

ImportProgress = Callable[[int, int, str], None]


@dataclass(frozen=True)
class ImportFileError:
    file_name: str
    reason: str


@dataclass(frozen=True)
class ImportResult:
    season: Season
    created: int
    skipped_duplicates: int
    episode_ids: list[int]
    scanned: int = 0
    errors: list[ImportFileError] = field(default_factory=list)


def import_season(
    session: Session,
    root_path: str | Path,
    title: str | None = None,
    progress_callback: ImportProgress | None = None,
) -> ImportResult:
    root = Path(root_path).expanduser().resolve(strict=False)
    season = session.scalar(select(Season).where(Season.root_path == str(root)))
    if season is None:
        season = Season(title=title or root.name or "Сезон", root_path=str(root))
        session.add(season)
        session.flush()

    media_paths = discover_video_files(root)
    total = len(media_paths)
    created = 0
    skipped = 0
    episode_ids: list[int] = []
    errors: list[ImportFileError] = []
    for index, media_path in enumerate(media_paths, start=1):
        if progress_callback is not None:
            progress_callback(index, total, media_path.name)
        try:
            fp = fingerprint_file(media_path)
        except OSError as exc:
            # A file locked by antivirus/Explorer/another process must not abort
            # the whole season import.
            logger.warning("Skipping unreadable episode during import: %s (%s)", media_path, exc)
            errors.append(ImportFileError(file_name=media_path.name, reason=str(exc)))
            continue
        existing = session.scalar(select(Episode).where(Episode.fingerprint == fp.value))
        if existing is not None:
            skipped += 1
            episode_ids.append(existing.id)
            continue
        episode = Episode(
            season_id=season.id,
            file_path=str(media_path),
            file_name=media_path.name,
            fingerprint=fp.value,
            size_bytes=fp.size_bytes,
            modified_ns=fp.modified_ns,
            stage=EpisodeStage.DISCOVERED.value,
        )
        session.add(episode)
        session.flush()
        created += 1
        episode_ids.append(episode.id)

    return ImportResult(
        season=season,
        created=created,
        skipped_duplicates=skipped,
        episode_ids=episode_ids,
        scanned=total,
        errors=errors,
    )

