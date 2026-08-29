from __future__ import annotations

from dataclasses import dataclass

from app.models.entities import TranscriptSegment


@dataclass(frozen=True)
class SubtitleCue:
    start_time: float
    end_time: float
    text: str


def cues_for_range(segments: list[TranscriptSegment], start_time: float, end_time: float) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    for segment in segments:
        if segment.end_time <= start_time or segment.start_time >= end_time:
            continue
        relative_start = max(0.0, segment.start_time - start_time)
        relative_end = max(relative_start + 0.2, min(end_time, segment.end_time) - start_time)
        for line in wrap_russian_subtitle(segment.text):
            cues.append(SubtitleCue(relative_start, relative_end, line))
    return cues


def wrap_russian_subtitle(text: str, max_chars: int = 34) -> list[str]:
    words = text.strip().split()
    if not words:
        return []
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and len(candidate) > max_chars:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    merged: list[str] = []
    for index in range(0, len(lines), 2):
        merged.append("\\N".join(lines[index : index + 2]))
    return merged


def render_srt(cues: list[SubtitleCue]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        text = cue.text.replace("\\N", "\n")
        blocks.append(f"{index}\n{_srt_time(cue.start_time)} --> {_srt_time(cue.end_time)}\n{text}\n")
    return "\n".join(blocks)


def render_ass(cues: list[SubtitleCue], font_name: str = "Segoe UI") -> str:
    header = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},64,&H00FFFFFF,&H00111111,&H99000000,0,0,0,0,100,100,0,0,1,5,1,2,72,72,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = [
        f"Dialogue: 0,{_ass_time(cue.start_time)},{_ass_time(cue.end_time)},Default,,0,0,0,,{cue.text}"
        for cue in cues
    ]
    return header + "\n".join(events) + ("\n" if events else "")


def _srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def _ass_time(seconds: float) -> str:
    centis = int(round(seconds * 100))
    hours, rem = divmod(centis, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{cs:02}"
