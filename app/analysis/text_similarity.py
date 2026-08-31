from __future__ import annotations

import re


_SYNONYM_GROUPS = [
    {"смерт", "погиб", "умер", "убий"},
    {"любов", "влюб", "отношен", "чувств"},
    {"тайн", "секрет", "скрыва", "правд", "раскры"},
    {"конфликт", "ссор", "спор", "драк", "противостоя"},
    {"предат", "обман", "измен", "лж"},
    {"побед", "выигр", "спас", "успех"},
    {"опасн", "угроз", "страх", "риск"},
    {"решен", "выбор", "решил", "поступ"},
]


def semantic_similarity(left: str, right: str) -> float:
    left_tokens = token_features(left)
    right_tokens = token_features(right)
    if not left_tokens or not right_tokens:
        return 0.0
    token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    left_chars = char_features(left)
    right_chars = char_features(right)
    char_score = (
        len(left_chars & right_chars) / len(left_chars | right_chars)
        if left_chars and right_chars
        else 0.0
    )
    return token_score * 0.72 + char_score * 0.28


def token_features(value: str) -> set[str]:
    words = _words(value)
    features = {_stem(word) for word in words}
    for feature in list(features):
        for index, group in enumerate(_SYNONYM_GROUPS):
            if any(feature.startswith(item) or item.startswith(feature) for item in group):
                features.add(f"synonym:{index}")
    return features


def char_features(value: str) -> set[str]:
    compact = " ".join(_words(value))
    return {compact[index : index + 3] for index in range(max(0, len(compact) - 2))}


def natural_key(value: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value))


def _words(value: str) -> list[str]:
    normalized = re.sub(r"[^a-zа-яё0-9]+", " ", value.casefold())
    return [word for word in normalized.split() if len(word) >= 3]


def _stem(word: str) -> str:
    for suffix in (
        "иями", "ями", "ами", "его", "ого", "ему", "ому", "ыми", "ими",
        "ией", "ий", "ый", "ая", "яя", "ое", "ее", "ов", "ев", "ах", "ях",
        "ам", "ям", "ом", "ем", "ы", "и", "а", "я", "у", "ю", "е", "о",
    ):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word
