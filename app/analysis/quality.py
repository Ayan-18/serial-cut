from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.schemas import CandidatePayload
from app.models.entities import ClipCandidate, Scene, TranscriptSegment, WordTimestamp


def calibrate_candidate(
    candidate: CandidatePayload,
    segments: list[TranscriptSegment],
    scenes: list[Scene],
    words: list[WordTimestamp],
) -> CandidatePayload:
    text = _range_text(segments, candidate.start_time, candidate.end_time)
    range_words = [word for word in words if candidate.start_time <= word.start_time <= candidate.end_time]
    range_scenes = [
        scene
        for scene in scenes
        if scene.end_time >= candidate.start_time and scene.start_time <= candidate.end_time
    ]
    duration = max(0.1, candidate.end_time - candidate.start_time)
    pauses = _speech_pauses(segments, candidate.start_time, candidate.end_time)

    cuts_start = any(
        item.start_time + 0.05 < candidate.start_time < item.end_time - 0.05 for item in segments
    )
    cuts_end = any(
        item.start_time + 0.05 < candidate.end_time < item.end_time - 0.05 for item in segments
    )
    completed_ending = text.rstrip().endswith((".", "!", "?", "…"))
    boundary = 38 if cuts_start or cuts_end else (94 if completed_ending else 62)
    opening = text[:180]
    hook = min(100, 64 + (11 if "?" in opening else 0) + (9 if "!" in opening else 0))
    hook -= 18 if _looks_like_recap_or_credits(opening, candidate.title, candidate.description) else 0
    standalone = _standalone_score(text, candidate.standalone_reason)
    payoff = _payoff_score(text, completed_ending)
    emotion = _emotion_score(text, candidate.moment_type)
    word_density = len(range_words) / duration
    audio = 92 if 0.8 <= word_density <= 4.5 else 68
    if any(pause >= 2.2 for pause in pauses):
        audio -= 14
    scene_rate = len(range_scenes) / max(1.0, duration / 10)
    visual = min(96, max(58, round(64 + scene_rate * 7)))
    if duration > 45 and len(range_scenes) <= 1:
        visual -= 6

    scores = candidate.scores.model_copy(
        update={
            "hook": round((candidate.scores.hook * 2 + hook) / 3),
            "standalone_context": round((candidate.scores.standalone_context + standalone) / 2),
            "payoff": round((candidate.scores.payoff + payoff) / 2),
            "emotion": round((candidate.scores.emotion * 2 + emotion) / 3),
            "boundary_quality": round((candidate.scores.boundary_quality + boundary) / 2),
            "visual_potential": round((candidate.scores.visual_potential * 2 + visual) / 3),
            "audio_quality": round((candidate.scores.audio_quality * 2 + audio) / 3),
        }
    )
    calibrated = round(
        scores.hook * 0.22
        + scores.standalone_context * 0.17
        + scores.payoff * 0.17
        + scores.emotion * 0.14
        + scores.boundary_quality * 0.12
        + scores.visual_potential * 0.10
        + scores.audio_quality * 0.08
    )
    problems = list(candidate.possible_problems)
    if cuts_start and len(problems) < 5:
        problems.append("Начало попадает в середину реплики")
    if cuts_end and len(problems) < 5:
        problems.append("Конец попадает в середину реплики")
    if boundary < 80 and len(problems) < 5:
        problems.append("Конец реплики может быть незавершённым")
    if audio < 80 and len(problems) < 5:
        problems.append("Проверьте паузы и плотность речи")
    if standalone < 70 and len(problems) < 5:
        problems.append("Момент может быть непонятен без контекста")
    if payoff < 70 and len(problems) < 5:
        problems.append("Слабая концовка для короткого ролика")
    return candidate.model_copy(update={"score": calibrated, "scores": scores, "possible_problems": problems})


def remove_cross_episode_duplicates(
    session: Session,
    episode_id: int,
    candidates: list[CandidatePayload],
    segments: list[TranscriptSegment],
    threshold: float = 0.84,
) -> list[CandidatePayload]:
    existing = session.scalars(select(ClipCandidate).where(ClipCandidate.episode_id != episode_id)).all()
    if not existing:
        return candidates
    segment_cache: dict[int, list[TranscriptSegment]] = {}
    result: list[CandidatePayload] = []
    for candidate in candidates:
        tokens = _tokens(_range_text(segments, candidate.start_time, candidate.end_time))
        duplicate = False
        for prior in existing:
            prior_segments = segment_cache.get(prior.episode_id)
            if prior_segments is None:
                prior_segments = session.scalars(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.episode_id == prior.episode_id)
                    .order_by(TranscriptSegment.start_time)
                ).all()
                segment_cache[prior.episode_id] = prior_segments
            prior_tokens = _tokens(_range_text(prior_segments, prior.start_time, prior.end_time))
            if prior.score >= candidate.score and _jaccard(tokens, prior_tokens) >= threshold:
                duplicate = True
                break
        if not duplicate:
            result.append(candidate)
    return result


def _range_text(segments: list[TranscriptSegment], start: float, end: float) -> str:
    return " ".join(
        item.text
        for item in segments
        if item.start_time >= start - 0.05 and item.end_time <= end + 0.05
    ).strip()


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[а-яёa-z0-9]+", text.casefold()) if len(token) > 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _speech_pauses(segments: list[TranscriptSegment], start: float, end: float) -> list[float]:
    selected = [
        item for item in sorted(segments, key=lambda segment: segment.start_time)
        if item.end_time >= start and item.start_time <= end
    ]
    return [
        max(0.0, right.start_time - left.end_time)
        for left, right in zip(selected, selected[1:])
    ]


def _looks_like_recap_or_credits(*parts: str) -> bool:
    text = " ".join(parts).casefold()
    markers = [
        "ранее в сериале",
        "в предыдущей серии",
        "заставк",
        "титр",
        "opening",
        "credits",
    ]
    return any(marker in text for marker in markers)


def _standalone_score(text: str, reason: str) -> int:
    tokens = _tokens(f"{text} {reason}")
    score = 62
    if len(tokens) >= 18:
        score += 12
    if any(marker in tokens for marker in {"деньги", "письмо", "секрет", "отец", "обман", "правда"}):
        score += 12
    if "?" in text:
        score += 5
    vague = {"это", "там", "тот", "она", "они", "него", "куда", "потом"}
    if len(tokens & vague) >= 4:
        score -= 8
    return max(35, min(96, score))


def _payoff_score(text: str, completed_ending: bool) -> int:
    tail = text[-220:].casefold()
    score = 58 + (18 if completed_ending else 0)
    if any(mark in tail for mark in ["?", "!", "правда", "жив", "у меня", "не могу", "никогда"]):
        score += 16
    if len(_tokens(tail)) < 8:
        score -= 8
    return max(30, min(98, score))


def _emotion_score(text: str, moment_type: str) -> int:
    emotional_markers = [
        "!",
        "правда",
        "скрывал",
        "разрушил",
        "защитить",
        "жив",
        "люблю",
        "ненавижу",
        "прости",
    ]
    text_cf = text.casefold()
    score = 56
    score += sum(7 for marker in emotional_markers if marker in text_cf)
    if moment_type in {"конфликт", "откровение", "эмоциональный момент", "напряжение"}:
        score += 12
    return max(35, min(98, score))
