from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import EpisodeStage
from app.infrastructure.filesystem import discover_video_files
from app.infrastructure.fingerprint import fingerprint_file
from app.models.entities import Episode, Season


@dataclass(frozen=True)
class ImportResult:
    season: Season
    created: int
    skipped_duplicates: int
    episode_ids: list[int]


def import_season(session: Session, root_path: str | Path, title: str | None = None) -> ImportResult:
    root = Path(root_path).expanduser().resolve(strict=False)
    season = session.scalar(select(Season).where(Season.root_path == str(root)))
    if season is None:
        season = Season(title=title or root.name or "Сезон", root_path=str(root))
        session.add(season)
        session.flush()

    created = 0
    skipped = 0
    episode_ids: list[int] = []
    for media_path in discover_video_files(root):
        fp = fingerprint_file(media_path)
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

    return ImportResult(season=season, created=created, skipped_duplicates=skipped, episode_ids=episode_ids)

