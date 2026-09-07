from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.entities import TranscriptSegment, WordTimestamp


SAFE_ZONE_MARGINS = {
    "standard": (72, 72, 220),
    "shorts": (90, 90, 320),
    "reels": (90, 90, 300),
    "high": (96, 96, 380),
}


@dataclass(frozen=True)
class SubtitleCue:
    start_time: float
    end_time: float
    text: str
    speaker_label: str | None = None
    # Per-word (start, end) relative to the clip, aligned to the whitespace/\\N
    # tokens of ``text``. Populated only on the word-timed path; empty otherwise,
    # in which case the animated renderer falls back to an even sweep.
    word_times: tuple[tuple[float, float], ...] = ()


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
    speaker_by_segment: dict[int, str | None] | None = None,
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
        speaker = (speaker_by_segment or {}).get(current[0].segment_id)
        cue_start = max(0.0, current[0].start_time - start_time)
        cue_end = max(0.2, min(end_time, current[-1].end_time) - start_time)
        word_times = tuple(
            (
                max(cue_start, word.start_time - start_time),
                max(cue_start, min(cue_end, word.end_time - start_time)),
            )
            for word in current
        )
        cues.append(
            SubtitleCue(
                start_time=cue_start,
                end_time=cue_end,
                text=cue_text,
                speaker_label=speaker,
                word_times=word_times if len(word_times) == _token_count(cue_text) else (),
            )
        )
        current.clear()

    for word in selected:
        proposed_words = [*(item.word.strip() for item in current), word.word.strip()]
        proposed_text = _join_subtitle_words(proposed_words)
        proposed_duration = word.end_time - (current[0].start_time if current else word.start_time)
        gap = word.start_time - current[-1].end_time if current else 0.0
        speaker_changed = bool(
            current
            and speaker_by_segment
            and speaker_by_segment.get(current[-1].segment_id) != speaker_by_segment.get(word.segment_id)
        )
        if current and (
            len(wrap_russian_subtitle(proposed_text, max_chars=max_chars_per_line)) > 1
            or proposed_duration > max_seconds
            or gap > 0.8
            or speaker_changed
        ):
            flush()
        current.append(word)
        if word.word.rstrip().endswith((".", "!", "?", "…")) and len(current) >= 3:
            flush()
    flush()
    return improve_cue_timing(cues, max(0.0, end_time - start_time))


def improve_cue_timing(
    cues: list[SubtitleCue],
    clip_duration: float,
    target_chars_per_second: float = 18.0,
) -> list[SubtitleCue]:
    result: list[SubtitleCue] = []
    for index, cue in enumerate(cues):
        text_length = len(cue.text.replace("\\N", " ").strip())
        desired = max(0.65, min(4.2, text_length / target_chars_per_second))
        next_start = cues[index + 1].start_time if index + 1 < len(cues) else clip_duration
        latest_end = max(cue.end_time, min(clip_duration, next_start - 0.04 if index + 1 < len(cues) else clip_duration))
        end = min(latest_end, max(cue.end_time, cue.start_time + desired))
        result.append(
            SubtitleCue(
                cue.start_time, max(cue.start_time + 0.2, end), cue.text, cue.speaker_label, cue.word_times
            )
        )
    return result


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


# The word lit up in animated mode: gold fill, brief scale-up "pop". Fixed for
# now — a per-project palette can come later.
_HIGHLIGHT_COLOUR = "&H0000D7FF"  # #FFD700 as ASS BGR
_ACTIVE_PREFIX = f"{{\\c{_HIGHLIGHT_COLOUR}\\fscx104\\fscy104\\t(0,120,\\fscx112\\fscy112)}}"


def render_ass(
    cues: list[SubtitleCue],
    font_name: str = "Segoe UI",
    font_size: int = 48,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    safe_zone: str = "standard",
    animate: bool = False,
) -> str:
    margin_l, margin_r, margin_v = _scaled_margins(safe_zone, play_res_x, play_res_y)
    font_name = _safe_ass_font_name(font_name)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H00111111,&H99000000,0,0,0,0,100,100,0,0,1,3,1,2,{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for cue in cues:
        if animate:
            events.extend(_animated_events(cue))
        else:
            events.append(
                f"Dialogue: 0,{_ass_time(cue.start_time)},{_ass_time(cue.end_time)},Default,,0,0,0,,"
                f"{_escape_ass_text(cue.text)}"
            )
    return header + "\n".join(events) + ("\n" if events else "")


_TOKEN_SPLIT = re.compile(r"(\\N|\s+)")


def _token_count(text: str) -> int:
    return sum(1 for part in _TOKEN_SPLIT.split(text) if part and not _TOKEN_SPLIT.fullmatch(part))


def _animated_events(cue: SubtitleCue) -> list[str]:
    """One Dialogue per word: the whole line is redrawn each time with the
    current word lit up, so the highlight tracks the audio without flicker.

    A cue that carries inline override tags (a bold speaker-name prefix) is left
    as one static event — animating around them is not worth it.
    """
    static = (
        f"Dialogue: 0,{_ass_time(cue.start_time)},{_ass_time(cue.end_time)},Default,,0,0,0,,"
        f"{_escape_ass_text(cue.text)}"
    )
    if "{" in cue.text:
        return [static]
    parts = [part for part in _TOKEN_SPLIT.split(cue.text) if part]
    word_indexes = [i for i, part in enumerate(parts) if not _TOKEN_SPLIT.fullmatch(part)]
    if len(word_indexes) < 2:
        return [static]

    if len(cue.word_times) == len(word_indexes):
        starts = [span[0] for span in cue.word_times]
    else:
        step = (cue.end_time - cue.start_time) / len(word_indexes)
        starts = [cue.start_time + i * step for i in range(len(word_indexes))]

    def rendered_part(index: int, part: str, active_index: int) -> str:
        if _TOKEN_SPLIT.fullmatch(part):  # separator: raw \N or literal spaces
            return part
        escaped = _escape_ass_text(part)
        return f"{_ACTIVE_PREFIX}{escaped}{{\\r}}" if index == active_index else escaped

    events: list[str] = []
    for order, active_part_index in enumerate(word_indexes):
        ev_start = cue.start_time if order == 0 else starts[order]
        ev_end = starts[order + 1] if order + 1 < len(word_indexes) else cue.end_time
        if ev_end <= ev_start:
            continue
        line = "".join(rendered_part(i, part, active_part_index) for i, part in enumerate(parts))
        events.append(f"Dialogue: 0,{_ass_time(ev_start)},{_ass_time(ev_end)},Default,,0,0,0,,{line}")
    return events or [static]


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


def _scaled_margins(safe_zone: str, play_res_x: int, play_res_y: int) -> tuple[int, int, int]:
    margin_l, margin_r, margin_v = SAFE_ZONE_MARGINS.get(safe_zone, SAFE_ZONE_MARGINS["standard"])
    x_scale = play_res_x / 1080
    y_scale = play_res_y / 1920
    return (
        max(16, round(margin_l * x_scale)),
        max(16, round(margin_r * x_scale)),
        max(24, round(margin_v * y_scale)),
    )


def _escape_ass_text(value: str) -> str:
    """Escape user/ASR text while preserving the few tags generated by SerialCuts."""
    placeholders = {
        "\ue000": "\\N",
        "\ue001": "{\\b1}",
        "\ue002": "{\\b0}",
    }
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("{\\b1}", "\ue001").replace("{\\b0}", "\ue002")
    text = text.replace("\\N", "\ue000").replace("\n", "\ue000")
    text = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    for placeholder, original in placeholders.items():
        text = text.replace(placeholder, original)
    return text


def _safe_ass_font_name(value: str) -> str:
    cleaned = re.sub(r"[\r\n,{}\\]+", " ", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:128] or "Segoe UI"
