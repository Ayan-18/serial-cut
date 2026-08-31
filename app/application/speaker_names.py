from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Character, SpeakerIdentity


def speaker_name_map(session: Session, episode_id: int) -> dict[str, str]:
    rows = session.execute(
        select(SpeakerIdentity.source_label, Character.name)
        .join(Character, Character.id == SpeakerIdentity.character_id)
        .where(SpeakerIdentity.episode_id == episode_id)
    ).all()
    return {source: name for source, name in rows}
