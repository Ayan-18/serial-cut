from __future__ import annotations

import re

# Cardinal number -> Russian words, for TTS pre-normalization. Small local models
# (Silero, SAPI) read bare digits badly. Gender defaults to masculine ("один",
# "два"); for narration prose that is right far more often than it is wrong.

_ONES = [
    "ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
    "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
    "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать",
]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
_HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
_SCALES = [
    ("", "", ""),
    ("тысяча", "тысячи", "тысяч"),
    ("миллион", "миллиона", "миллионов"),
    ("миллиард", "миллиарда", "миллиардов"),
]


def _triplet_words(value: int, feminine: bool) -> list[str]:
    words: list[str] = []
    if value >= 100:
        words.append(_HUNDREDS[value // 100])
        value %= 100
    if value >= 20:
        words.append(_TENS[value // 10])
        value %= 10
    if value:
        if value == 1:
            words.append("одна" if feminine else "один")
        elif value == 2:
            words.append("две" if feminine else "два")
        else:
            words.append(_ONES[value])
    return words


def _plural_form(value: int, forms: tuple[str, str, str]) -> str:
    v = value % 100
    if 11 <= v <= 14:
        return forms[2]
    v %= 10
    if v == 1:
        return forms[0]
    if 2 <= v <= 4:
        return forms[1]
    return forms[2]


def cardinal(value: int) -> str:
    if value == 0:
        return _ONES[0]
    if value < 0:
        return "минус " + cardinal(-value)
    triplets: list[int] = []
    while value:
        triplets.append(value % 1000)
        value //= 1000
    parts: list[str] = []
    for scale, triplet in reversed(list(enumerate(triplets))):
        if not triplet:
            continue
        parts.extend(_triplet_words(triplet, feminine=scale == 1))
        if scale > 0:
            parts.append(_plural_form(triplet, _SCALES[scale]))
    return " ".join(parts)


_PERCENT_FORMS = ("процент", "процента", "процентов")


def _replace_number(match: re.Match) -> str:
    raw = match.group("num")
    suffix = match.group("suffix") or ""
    try:
        value = int(raw)
    except ValueError:
        return match.group(0)
    if len(raw) > 9:  # IDs / long codes — leave them as digits
        return match.group(0)
    words = cardinal(value)
    if suffix == "%":
        return f"{words} {_plural_form(value, _PERCENT_FORMS)}"
    return words


# Match a run of digits that is not part of a decimal / thousands-grouped number
# ("3.14", "1,5", "1 000"), not glued to letters/digits, and not a phone (+7…).
_NUMBER_RE = re.compile(r"(?<![\d.,+])(?P<num>\d{1,15})(?P<suffix>%)?(?![.,]?\d)")


def normalize_numbers(text: str) -> str:
    """Spell out standalone integers (and N%) so a local TTS reads them aloud."""
    return _NUMBER_RE.sub(_replace_number, text)
