from __future__ import annotations

from dataclasses import dataclass

from app.models.entities import TranscriptSegment, WordTimestamp


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
        pages = wrap_russian_subtitle(segment.text)
        weights = [max(1, len(page.replace("\\N", " ").split())) for page in pages]
        total_weight = sum(weights)
        elapsed_weight = 0
        for page, weight in zip(pages, weights, strict=True):
            cue_start = relative_start + (relative_end - relative_start) * elapsed_weight / total_weight
            elapsed_weight += weight
            cue_end = relative_start + (relative_end - relative_start) * elapsed_weight / total_weight
            cues.append(SubtitleCue(cue_start, cue_end, page))
    return cues


def cues_for_words(
    words: list[WordTimestamp],
    start_time: float,
    end_time: float,
    max_chars_per_line: int = 30,
    max_seconds: float = 3.2,
) -> list[SubtitleCue]:
    selected = [
        word
        for word in words
        if word.end_time > start_time and word.start_time < end_time and word.word.strip()
    ]
    cues: list[SubtitleCue] = []
    current: list[WordTimestamp] = []

    def flush() -> None:
        if not current:
            return
        text = _join_subtitle_words([word.word.strip() for word in current])
        pages = wrap_russian_subtitle(text, max_chars=max_chars_per_line)
        cue_text = pages[0] if pages else text
        cues.append(
            SubtitleCue(
                start_time=max(0.0, current[0].start_time - start_time),
                end_time=max(0.2, min(end_time, current[-1].end_time) - start_time),
                text=cue_text,
            )
        )
        current.clear()

    for word in selected:
        proposed_words = [*(item.word.strip() for item in current), word.word.strip()]
        proposed_text = _join_subtitle_words(proposed_words)
        proposed_duration = word.end_time - (current[0].start_time if current else word.start_time)
        gap = word.start_time - current[-1].end_time if current else 0.0
        if current and (
            len(wrap_russian_subtitle(proposed_text, max_chars=max_chars_per_line)) > 1
            or proposed_duration > max_seconds
            or gap > 0.8
        ):
            flush()
        current.append(word)
    flush()
    return cues


def _join_subtitle_words(words: list[str]) -> str:
    text = ""
    no_space_before = set(".,!?;:%)]}»")
    no_space_after = set("([{«")
    for word in words:
        if not text or word[:1] in no_space_before or text[-1:] in no_space_after:
            text += word
        else:
            text += " " + word
    return text


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


def render_ass(
    cues: list[SubtitleCue],
    font_name: str = "Segoe UI",
    font_size: int = 48,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
) -> str:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H00111111,&H99000000,0,0,0,0,100,100,0,0,1,3,1,2,72,72,220,1

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
