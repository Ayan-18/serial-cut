from __future__ import annotations

from app.domain.enums import TrackKind
from app.models.entities import MediaTrack


RUSSIAN_LANGUAGE_CODES = {"ru", "rus", "russian", "рус", "русский"}


def select_russian_audio_track(tracks: list[MediaTrack]) -> MediaTrack | None:
    audio_tracks = [track for track in tracks if track.kind == TrackKind.AUDIO.value]
    return _select_russian_track(audio_tracks) or (audio_tracks[0] if audio_tracks else None)


def select_russian_subtitle_track(tracks: list[MediaTrack]) -> MediaTrack | None:
    subtitle_tracks = [track for track in tracks if track.kind == TrackKind.SUBTITLE.value]
    return _select_russian_track(subtitle_tracks)


def _select_russian_track(tracks: list[MediaTrack]) -> MediaTrack | None:
    for track in tracks:
        if _looks_russian(track.language) or _looks_russian(track.title):
            return track
    return None


def _looks_russian(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().lower()
    return normalized in RUSSIAN_LANGUAGE_CODES or "рус" in normalized or "russian" in normalized

