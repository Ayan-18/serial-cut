from __future__ import annotations

from app.domain.enums import TrackKind
from app.media.tracks import select_russian_audio_track, select_russian_subtitle_track
from app.models.entities import MediaTrack


def test_selects_russian_audio_track_by_language():
    tracks = [
        MediaTrack(stream_index=1, kind=TrackKind.AUDIO.value, language="eng"),
        MediaTrack(stream_index=2, kind=TrackKind.AUDIO.value, language="rus"),
    ]

    assert select_russian_audio_track(tracks).stream_index == 2


def test_selects_russian_subtitle_track_by_title():
    tracks = [
        MediaTrack(stream_index=3, kind=TrackKind.SUBTITLE.value, title="English"),
        MediaTrack(stream_index=4, kind=TrackKind.SUBTITLE.value, title="Русские субтитры"),
    ]

    assert select_russian_subtitle_track(tracks).stream_index == 4

