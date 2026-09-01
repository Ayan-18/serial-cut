from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.media.tts import (
    DEFAULT_FEMALE_VOICE,
    DEFAULT_MALE_VOICE,
    DEFAULT_NARRATOR_VOICE,
    SILERO_VOICE_IDS,
)
from app.models.entities import Character, StoryArc

_MALE_HINTS = (
    "мужчина", "муж.", "мужчин", "парень", "юноша", "мальчик", "брат", "отец", "папа",
    "сын", "дед", "король", "царь", "принц", "он ", "его ", "ему ",
)
_FEMALE_HINTS = (
    "женщина", "жен.", "женщин", "девушка", "девочка", "сестра", "мать", "мама",
    "дочь", "бабушка", "королева", "царица", "принцесса", "она ", "её ", "ей ",
)


def guess_character_gender(character: Character) -> str:
    """Best-effort "male" / "female" / "unknown" from description and name."""
    text = f" {character.description or ''} ".lower()
    male = sum(hint in text for hint in _MALE_HINTS)
    female = sum(hint in text for hint in _FEMALE_HINTS)
    if male > female:
        return "male"
    if female > male:
        return "female"
    name = (character.name or "").strip().lower()
    first = name.split()[0] if name else ""
    if first and first not in {"никита", "илья", "фома", "лука", "кузьма", "савва", "данила"}:
        if re.search(r"(а|я)$", first):
            return "female"
    if first and re.search(r"[бвгдйзклмнпрстфхцчшщ]$", first):
        return "male"
    return "unknown"


def auto_voice_for_character(character: Character, narrator_voice: str) -> str:
    gender = guess_character_gender(character)
    if gender == "male":
        return DEFAULT_MALE_VOICE
    if gender == "female":
        return DEFAULT_FEMALE_VOICE
    return narrator_voice or DEFAULT_NARRATOR_VOICE


def resolve_narration_voice(
    session: Session,
    arc: StoryArc,
    narration_mode: str,
    narrator_voice: str = DEFAULT_NARRATOR_VOICE,
) -> str:
    """Silero speaker id for this arc's narration line voice."""
    narrator_voice = narrator_voice if narrator_voice in SILERO_VOICE_IDS else DEFAULT_NARRATOR_VOICE
    if narration_mode != "first_person" or not arc.target_character_id:
        return narrator_voice
    character = session.get(Character, arc.target_character_id)
    if character is None:
        return narrator_voice
    if character.narration_voice and character.narration_voice in SILERO_VOICE_IDS:
        return character.narration_voice
    return auto_voice_for_character(character, narrator_voice)
