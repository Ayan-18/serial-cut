from __future__ import annotations


from app.media.subtitles import SubtitleCue, cues_for_words, render_ass
from app.models.entities import WordTimestamp


def _word(seg: int, start: float, end: float, text: str) -> WordTimestamp:
    return WordTimestamp(segment_id=seg, start_time=start, end_time=end, word=text)


def test_render_ass_plain_emits_one_event_per_cue():
    cues = [SubtitleCue(0.0, 1.5, "Привет мир"), SubtitleCue(1.5, 3.0, "Как дела")]

    ass = render_ass(cues)

    assert ass.count("\nDialogue:") + ass.count("Events]\nDialogue:") == 2
    assert "Привет мир" in ass


def test_render_ass_animated_lights_up_one_word_at_a_time():
    cue = SubtitleCue(0.0, 1.2, "Один два три", word_times=((0.0, 0.4), (0.4, 0.8), (0.8, 1.2)))

    ass = render_ass([cue], animate=True)

    events = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(events) == 3  # one per word
    # every event still shows the whole line, exactly one word highlighted
    for event in events:
        body = event.split(",,", 1)[1]
        assert body.count("\\c&H0000D7FF") == 1
        assert "Один" in body and "два" in body and "три" in body
    # the highlight walks left to right
    assert "\\c&H0000D7FF\\fscx104\\fscy104\\t(0,120,\\fscx112\\fscy112)}Один{\\r}" in events[0]
    assert "}два{\\r}" in events[1]
    assert "}три{\\r}" in events[2]


def test_render_ass_animated_falls_back_to_even_sweep_without_word_times():
    cue = SubtitleCue(0.0, 2.0, "раз два три четыре")  # no word_times

    events = [line for line in render_ass([cue], animate=True).splitlines() if line.startswith("Dialogue:")]

    assert len(events) == 4
    assert events[0].startswith("Dialogue: 0,0:00:00.00,0:00:00.50,")  # 2.0s / 4 words


def test_render_ass_animated_keeps_speaker_prefixed_cues_static():
    cue = SubtitleCue(0.0, 1.5, "{\\b1}Аня:{\\b0}\\NПривет мир")

    events = [line for line in render_ass([cue], animate=True).splitlines() if line.startswith("Dialogue:")]

    assert len(events) == 1  # inline tags -> not animated
    assert "\\b1" in events[0]


def test_render_ass_animated_handles_a_two_line_cue():
    cue = SubtitleCue(0.0, 1.0, "первая строка\\Nвторая строка")

    events = [line for line in render_ass([cue], animate=True).splitlines() if line.startswith("Dialogue:")]

    assert len(events) == 4
    assert all("\\N" in line for line in events)  # the line break survives every frame


def test_cues_for_words_attaches_per_word_timing():
    words = [
        _word(1, 5.0, 5.3, "Смотри"),
        _word(1, 5.3, 5.6, "какой"),
        _word(1, 5.6, 6.0, "гол"),
    ]

    cues = cues_for_words(words, start_time=4.0, end_time=10.0)

    assert len(cues) == 1
    flat = [round(value, 3) for span in cues[0].word_times for value in span]
    assert flat == [1.0, 1.3, 1.3, 1.6, 1.6, 2.0]
    assert render_ass(cues, animate=True).count("\\c&H0000D7FF") == 3
