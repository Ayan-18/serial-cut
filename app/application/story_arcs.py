from __future__ import annotations

import json
from dataclasses import dataclass, replace

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.analysis.text_similarity import natural_key, semantic_similarity
from app.analysis.local_text import generate_local_text
from app.analysis.schemas import extract_json_object
from app.infrastructure.config import Settings
from app.models.entities import (
    Character,
    ClipCandidate,
    Episode,
    PublishingPlan,
    Season,
    SpeakerIdentity,
    StoryArc,
    StoryArcExport,
    StoryArcSegment,
    TranscriptSegment,
)


@dataclass(frozen=True)
class StoryArcPlanRequest:
    season_id: int
    title: str | None = None
    prompt: str = ""
    arc_type: str = "custom"
    output_format: str = "shorts_series"
    target_character_id: int | None = None
    max_segments: int = 8
    max_duration_seconds: int = 420


@dataclass(frozen=True)
class StoryArcBuildItem:
    candidate: ClipCandidate
    episode: Episode
    score: float
    reason: str


@dataclass(frozen=True)
class StoryArcDeleteArtifacts:
    paths: list[str]
    publishing_plan_ids: list[int]


@dataclass(frozen=True)
class StoryArcUpdate:
    title: str | None = None
    prompt: str | None = None
    output_format: str | None = None
    status: str | None = None
    narration: list[dict] | None = None


@dataclass(frozen=True)
class StoryArcSegmentUpdate:
    sort_order: int | None = None
    start_time: float | None = None
    end_time: float | None = None
    title: str | None = None
    note: str | None = None
    role: str | None = None


def create_story_arc_plan(
    session: Session,
    request: StoryArcPlanRequest,
    settings: Settings | None = None,
) -> StoryArc:
    season = session.get(Season, request.season_id)
    if season is None:
        raise ValueError("Сезон не найден")
    character = _target_character(session, request.target_character_id, season.id)
    candidates = _rank_candidates(session, season.id, request.prompt, character)
    if not candidates:
        raise ValueError("Для сезонной арки нужны готовые кандидаты. Сначала выполните поиск кандидатов по сериям сезона.")

    selected = _select_arc_items(
        candidates,
        max_segments=max(1, request.max_segments),
        max_duration_seconds=max(15, request.max_duration_seconds),
    )
    if settings is not None and settings.llm_adapter != "stub":
        selected = _llm_story_order(settings, season, request, candidates, selected)
    if not selected:
        raise ValueError("Не удалось собрать арку в заданную длительность")

    title = _arc_title(request, season, character)
    arc = StoryArc(
        season_id=season.id,
        title=title,
        prompt=request.prompt.strip(),
        arc_type=request.arc_type,
        output_format=request.output_format,
        target_character_id=character.id if character else None,
        status="draft",
    )
    session.add(arc)
    session.flush()
    _replace_segments(session, arc, selected)
    arc.total_duration_seconds = round(sum(item.candidate.end_time - item.candidate.start_time for item in selected), 3)
    arc.plan_json = _plan_json(arc, season, character, selected, request)
    session.flush()
    return _load_arc(session, arc.id)


def list_story_arcs(session: Session, season_id: int | None = None) -> list[StoryArc]:
    query = select(StoryArc).options(selectinload(StoryArc.segments)).order_by(StoryArc.updated_at.desc(), StoryArc.id.desc())
    if season_id is not None:
        query = query.where(StoryArc.season_id == season_id)
    return list(session.scalars(query).all())


def get_story_arc(session: Session, story_arc_id: int) -> StoryArc:
    return _load_arc(session, story_arc_id)


def delete_story_arc(session: Session, story_arc_id: int) -> StoryArcDeleteArtifacts:
    arc = session.get(StoryArc, story_arc_id)
    if arc is None:
        raise ValueError("Арка не найдена")
    exports = session.scalars(
        select(StoryArcExport).where(StoryArcExport.story_arc_id == story_arc_id)
    ).all()
    paths = [
        value
        for item in exports
        for value in (item.output_path, item.metadata_path, item.cover_path)
        if value
    ]
    plan = dict(arc.plan_json or {})
    paths.extend(
        str(value)
        for value in (plan.get("narration_audio_path"), plan.get("narration_script_path"))
        if value
    )
    publishing_plan_ids = list(
        session.scalars(
            select(PublishingPlan.id).where(PublishingPlan.story_arc_id == story_arc_id)
        ).all()
    )
    session.delete(arc)
    session.flush()
    return StoryArcDeleteArtifacts(paths=paths, publishing_plan_ids=publishing_plan_ids)


def update_story_arc(session: Session, story_arc_id: int, patch: StoryArcUpdate) -> StoryArc:
    arc = _load_arc(session, story_arc_id)
    changed = False
    if patch.title is not None and patch.title.strip():
        value = patch.title.strip()
        changed = changed or value != arc.title
        arc.title = value
    if patch.prompt is not None:
        value = patch.prompt.strip()
        changed = changed or value != arc.prompt
        arc.prompt = value
    if patch.output_format is not None:
        changed = changed or patch.output_format != arc.output_format
        arc.output_format = patch.output_format
    if patch.status is not None:
        arc.status = patch.status
    if patch.narration is not None:
        plan = dict(arc.plan_json or {})
        plan["narration"] = patch.narration
        plan["narration_custom"] = True
        arc.plan_json = plan
        changed = True
    refresh_story_arc_plan(session, arc)
    if changed:
        _touch_arc(session, arc)
    session.flush()
    return _load_arc(session, arc.id)


def update_story_arc_segment(
    session: Session,
    story_arc_id: int,
    segment_id: int,
    patch: StoryArcSegmentUpdate,
) -> StoryArc:
    arc = _load_arc(session, story_arc_id)
    segment = next((item for item in arc.segments if item.id == segment_id), None)
    if segment is None:
        raise ValueError("Сегмент не найден в этой арке")
    target_order = max(1, patch.sort_order) if patch.sort_order is not None else None
    if patch.start_time is not None:
        segment.start_time = max(0.0, patch.start_time)
    if patch.end_time is not None:
        segment.end_time = patch.end_time
    segment.start_time, segment.end_time = _validated_segment_range(
        session, segment.episode_id, segment.start_time, segment.end_time
    )
    if patch.title is not None and patch.title.strip():
        segment.title = patch.title.strip()
    if patch.note is not None:
        segment.note = patch.note.strip()
    if patch.role is not None:
        segment.role = patch.role.strip() or None
    segment.manually_edited = True
    if segment.candidate is not None:
        segment.candidate_revision = segment.candidate.edit_revision
    if target_order is not None:
        _move_segment(arc, segment, target_order)
    else:
        _normalize_segment_order(arc)
    refresh_story_arc_plan(session, arc)
    _touch_arc(session, arc)
    session.flush()
    return _load_arc(session, arc.id)


def remove_story_arc_segment(session: Session, story_arc_id: int, segment_id: int) -> StoryArc:
    arc = _load_arc(session, story_arc_id)
    segment = next((item for item in arc.segments if item.id == segment_id), None)
    if segment is None:
        raise ValueError("Сегмент не найден в этой арке")
    session.delete(segment)
    session.flush()
    arc = _load_arc(session, story_arc_id)
    _normalize_segment_order(arc)
    refresh_story_arc_plan(session, arc)
    _touch_arc(session, arc)
    session.flush()
    return _load_arc(session, arc.id)


def prune_episode_from_story_arcs(session: Session, episode_id: int) -> None:
    """Drop every StoryArc segment that points at ``episode_id`` and refresh the
    affected plans so a deleted series cannot leave dangling montage rows."""
    arc_ids = list(
        session.scalars(
            select(StoryArcSegment.story_arc_id)
            .where(StoryArcSegment.episode_id == episode_id)
            .distinct()
        ).all()
    )
    if not arc_ids:
        return
    session.execute(delete(StoryArcSegment).where(StoryArcSegment.episode_id == episode_id))
    session.flush()
    for arc_id in arc_ids:
        arc = session.scalar(
            select(StoryArc)
            .options(selectinload(StoryArc.segments), selectinload(StoryArc.exports))
            .where(StoryArc.id == arc_id)
        )
        if arc is None:
            continue
        _normalize_segment_order(arc)
        refresh_story_arc_plan(session, arc)
        _touch_arc(session, arc)
    session.flush()


def add_candidate_to_story_arc(session: Session, story_arc_id: int, candidate_id: int) -> StoryArc:
    arc = _load_arc(session, story_arc_id)
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError("Кандидат не найден")
    episode = session.get(Episode, candidate.episode_id)
    if episode is None or episode.season_id != arc.season_id:
        raise ValueError("Кандидат должен быть из того же сезона")
    if any(item.candidate_id == candidate.id for item in arc.segments):
        return arc
    next_order = max((segment.sort_order for segment in arc.segments), default=0) + 1
    segment = StoryArcSegment(
        story_arc_id=arc.id,
        episode_id=episode.id,
        candidate_id=candidate.id,
        sort_order=next_order,
        start_time=candidate.start_time,
        end_time=candidate.end_time,
        title=candidate.title,
        note="Добавлено вручную из поиска",
        role=candidate.story_role or _default_arc_role(next_order, next_order),
        candidate_revision=candidate.edit_revision,
        manually_edited=True,
    )
    session.add(segment)
    session.flush()
    arc = _load_arc(session, arc.id)
    refresh_story_arc_plan(session, arc)
    _touch_arc(session, arc)
    session.flush()
    return _load_arc(session, arc.id)


def rebuild_story_arc_plan(
    session: Session,
    story_arc_id: int,
    settings: Settings | None = None,
) -> StoryArc:
    arc = _load_arc(session, story_arc_id)
    season = session.get(Season, arc.season_id)
    if season is None:
        raise ValueError("Сезон не найден")
    constraints = dict((arc.plan_json or {}).get("constraints") or {})
    request = StoryArcPlanRequest(
        season_id=arc.season_id,
        title=arc.title,
        prompt=arc.prompt,
        arc_type=arc.arc_type,
        output_format=arc.output_format,
        target_character_id=arc.target_character_id,
        max_segments=max(1, int(constraints.get("max_segments") or len(arc.segments))),
        max_duration_seconds=max(
            15,
            int(constraints.get("max_duration_seconds") or round(arc.total_duration_seconds)),
        ),
    )
    character = _target_character(session, request.target_character_id, arc.season_id)
    candidates = _rank_candidates(session, arc.season_id, request.prompt, character)
    preserved = [item for item in arc.segments if item.manually_edited]
    preserved_candidate_ids = {item.candidate_id for item in preserved if item.candidate_id is not None}
    preserved_duration = sum(item.end_time - item.start_time for item in preserved)
    remaining_candidates = [item for item in candidates if item.candidate.id not in preserved_candidate_ids]
    remaining_request = replace(
        request,
        max_segments=max(0, request.max_segments - len(preserved)),
        max_duration_seconds=max(0, request.max_duration_seconds - round(preserved_duration)),
    )
    selected = _select_arc_items(
        remaining_candidates,
        remaining_request.max_segments,
        remaining_request.max_duration_seconds,
    )
    if settings is not None and settings.llm_adapter != "stub":
        selected = _llm_story_order(settings, season, remaining_request, remaining_candidates, selected)
    if not selected and not preserved:
        raise ValueError("Не удалось пересобрать арку")
    _replace_segments(session, arc, selected, preserved=preserved)
    session.expire(arc, ["segments"])
    _normalize_segment_order(arc)
    refresh_story_arc_plan(session, arc, regenerate_narration=True)
    _touch_arc(session, arc)
    session.flush()
    return _load_arc(session, arc.id)


def _rank_candidates(
    session: Session,
    season_id: int,
    prompt: str,
    character: Character | None,
) -> list[StoryArcBuildItem]:
    rows = session.execute(
        select(ClipCandidate, Episode)
        .join(Episode, Episode.id == ClipCandidate.episode_id)
        .where(Episode.season_id == season_id)
        .where(ClipCandidate.status != "rejected")
        .order_by(Episode.file_name, ClipCandidate.start_time)
    ).all()
    speaker_labels = _character_speaker_labels(session, season_id, character.id) if character else {}
    prompt_terms = _terms(prompt)
    items: list[StoryArcBuildItem] = []
    for candidate, episode in rows:
        text = " ".join(
            [
                candidate.title,
                candidate.description,
                candidate.moment_type,
                candidate.rationale,
                candidate.continuity_note or "",
                episode.story_summary,
            ]
        )
        score = float(candidate.score)
        reasons: list[str] = [f"score {candidate.score}"]
        if candidate.story_order is not None:
            score += 5
            reasons.append("есть роль в сюжетном режиме")
        if prompt_terms:
            matches = sum(1 for term in prompt_terms if term in text.lower())
            semantic = semantic_similarity(prompt, text)
            if matches:
                score += min(20, matches * 5)
                reasons.append(f"совпадений с запросом: {matches}")
            if semantic >= 0.18:
                score += min(18, round(semantic * 30))
                reasons.append(f"смысловая близость: {round(semantic * 100)}%")
        labels = speaker_labels.get(episode.id, set())
        if labels and _candidate_has_speaker(session, candidate, labels):
            score += 18
            reasons.append(f"есть реплики персонажа {character.name if character else ''}".strip())
        duration = candidate.end_time - candidate.start_time
        if duration < 12:
            score -= 8
            reasons.append("очень короткий кусок")
        if candidate.problems_json:
            score -= min(12, len(candidate.problems_json) * 3)
            reasons.append("есть замечания к кандидату")
        if candidate.status in {"approved", "rendered"}:
            score += 5
            reasons.append("подтверждено пользователем")
        items.append(StoryArcBuildItem(candidate, episode, score, ", ".join(reasons)))
    return sorted(items, key=lambda item: item.score, reverse=True)


def _select_arc_items(
    candidates: list[StoryArcBuildItem],
    max_segments: int,
    max_duration_seconds: int,
) -> list[StoryArcBuildItem]:
    if max_segments <= 0 or max_duration_seconds <= 0:
        return []
    selected: list[StoryArcBuildItem] = []
    per_episode: dict[int, int] = {}
    total = 0.0
    for item in candidates:
        duration = item.candidate.end_time - item.candidate.start_time
        if len(selected) >= max_segments:
            break
        if total + duration > max_duration_seconds and selected:
            continue
        if per_episode.get(item.episode.id, 0) >= 2 and len(selected) < min(max_segments, 4):
            continue
        if any(
            item.episode.id == kept.episode.id
            and _candidate_similarity(item.candidate, kept.candidate) >= 0.82
            for kept in selected
        ):
            continue
        selected.append(item)
        per_episode[item.episode.id] = per_episode.get(item.episode.id, 0) + 1
        total += duration
    return sorted(selected, key=lambda item: (natural_key(item.episode.file_name), item.candidate.start_time))


def _llm_story_order(
    settings: Settings,
    season: Season,
    request: StoryArcPlanRequest,
    candidates: list[StoryArcBuildItem],
    fallback: list[StoryArcBuildItem],
) -> list[StoryArcBuildItem]:
    pool = candidates[: min(len(candidates), max(request.max_segments * 3, request.max_segments))]
    rows = "\n".join(
        f"id={item.candidate.id}; серия={item.episode.file_name}; время={item.candidate.start_time:.1f}; "
        f"название={item.candidate.title}; описание={item.candidate.description}; "
        f"роль={item.candidate.story_role or 'не задана'}; связность={item.candidate.continuity_note or ''}"
        for item in pool
    )
    prompt = (
        "Выбери и упорядочи фрагменты в цельную причинно-следственную историю. Удали смысловые "
        "повторы, не ставь следствие раньше причины и закончи понятным итогом. Верни только JSON "
        "вида {\"candidate_ids\":[1,2]}. Используй только перечисленные id.\n\n"
        f"Сезон: {season.title}\nКонтекст: {season.story_context or 'не задан'}\n"
        f"Задача: {request.prompt or request.arc_type}\nКандидаты:\n{rows}"
    )
    raw = generate_local_text(settings, prompt, max_tokens=600)
    if not raw:
        return fallback
    try:
        ids = json.loads(extract_json_object(raw)).get("candidate_ids", [])
        ids = [int(item) for item in ids]
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return fallback
    by_id = {item.candidate.id: item for item in pool}
    selected: list[StoryArcBuildItem] = []
    duration = 0.0
    for candidate_id in ids:
        item = by_id.get(candidate_id)
        if item is None or item in selected or len(selected) >= request.max_segments:
            continue
        item_duration = item.candidate.end_time - item.candidate.start_time
        if duration + item_duration > request.max_duration_seconds and selected:
            continue
        if any(
            item.episode.id == prior.episode.id
            and _candidate_similarity(item.candidate, prior.candidate) >= 0.82
            for prior in selected
        ):
            continue
        selected.append(item)
        duration += item_duration
    return selected or fallback


def _replace_segments(
    session: Session,
    arc: StoryArc,
    items: list[StoryArcBuildItem],
    preserved: list[StoryArcSegment] | None = None,
) -> None:
    preserved = preserved or []
    preserved_ids = [item.id for item in preserved]
    query = delete(StoryArcSegment).where(StoryArcSegment.story_arc_id == arc.id)
    if preserved_ids:
        query = query.where(StoryArcSegment.id.not_in(preserved_ids))
    session.execute(query)
    next_order = max((item.sort_order for item in preserved), default=0)
    total_count = len(preserved) + len(items)
    for index, item in enumerate(items, start=next_order + 1):
        candidate = item.candidate
        session.add(
            StoryArcSegment(
                story_arc_id=arc.id,
                episode_id=item.episode.id,
                candidate_id=candidate.id,
                sort_order=index,
                start_time=candidate.start_time,
                end_time=candidate.end_time,
                title=candidate.title,
                note=item.reason,
                role=candidate.story_role or _default_arc_role(index, total_count),
                candidate_revision=candidate.edit_revision,
            )
        )
    session.flush()


def _plan_json(
    arc: StoryArc,
    season: Season,
    character: Character | None,
    items: list[StoryArcBuildItem],
    request: StoryArcPlanRequest,
) -> dict:
    chapters = [
        {
            "order": index,
            "episode_id": item.episode.id,
            "episode": item.episode.file_name,
            "candidate_id": item.candidate.id,
            "title": item.candidate.title,
            "range": [item.candidate.start_time, item.candidate.end_time],
            "duration": round(item.candidate.end_time - item.candidate.start_time, 3),
            "role": item.candidate.story_role or _default_arc_role(index, len(items)),
            "reason": item.reason,
        }
        for index, item in enumerate(items, start=1)
    ]
    return {
        "season": season.title,
        "arc": arc.title,
        "target_character": character.name if character else None,
        "format": arc.output_format,
        "constraints": {
            "max_segments": max(1, request.max_segments),
            "max_duration_seconds": max(15, request.max_duration_seconds),
        },
        "total_duration_seconds": round(sum(item["duration"] for item in chapters), 3),
        "chapters": chapters,
        "narration": _narration_plan(character, chapters),
        "next_step": "Проверьте порядок и границы, затем можно рендерить multi-source StoryArc.",
    }


def refresh_story_arc_plan(
    session: Session,
    arc: StoryArc,
    regenerate_narration: bool = False,
) -> None:
    season = session.get(Season, arc.season_id)
    character = _target_character(session, arc.target_character_id, arc.season_id) if arc.target_character_id else None
    chapters: list[dict] = []
    for index, segment in enumerate(sorted(arc.segments, key=lambda item: item.sort_order), start=1):
        episode = session.get(Episode, segment.episode_id)
        duration = max(0.0, segment.end_time - segment.start_time)
        chapters.append(
            {
                "order": index,
                "episode_id": segment.episode_id,
                "episode": episode.file_name if episode else "",
                "candidate_id": segment.candidate_id,
                "title": segment.title,
                "range": [segment.start_time, segment.end_time],
                "duration": round(duration, 3),
                "role": segment.role,
                "reason": segment.note,
            }
        )
    existing_plan = dict(arc.plan_json or {})
    narration_custom = bool(existing_plan.get("narration_custom"))
    narration = existing_plan.get("narration")
    arc.total_duration_seconds = round(sum(item["duration"] for item in chapters), 3)
    arc.plan_json = {
        **existing_plan,
        "season": season.title if season else "",
        "arc": arc.title,
        "target_character": character.name if character else None,
        "format": arc.output_format,
        "total_duration_seconds": arc.total_duration_seconds,
        "chapters": chapters,
        "narration": (
            narration
            if narration_custom and not regenerate_narration
            else _narration_plan(character, chapters)
        ),
        "narration_custom": narration_custom and not regenerate_narration,
    }


def _touch_arc(session: Session, arc: StoryArc) -> None:
    arc.edit_revision += 1
    arc.status = "draft"
    plan = dict(arc.plan_json or {})
    plan.pop("narration_audio_path", None)
    plan.pop("narration_script_path", None)
    arc.plan_json = plan
    for export in arc.exports:
        export.status = "stale"


def _normalize_segment_order(arc: StoryArc) -> None:
    for index, segment in enumerate(sorted(arc.segments, key=lambda item: (item.sort_order, item.id)), start=1):
        segment.sort_order = index


def _move_segment(arc: StoryArc, segment: StoryArcSegment, target_order: int) -> None:
    ordered = [item for item in sorted(arc.segments, key=lambda item: (item.sort_order, item.id)) if item.id != segment.id]
    ordered.insert(min(max(target_order - 1, 0), len(ordered)), segment)
    for index, item in enumerate(ordered, start=1):
        item.sort_order = index


def _target_character(session: Session, character_id: int | None, season_id: int) -> Character | None:
    if character_id is None:
        return None
    character = session.get(Character, character_id)
    if character is None or character.season_id != season_id:
        raise ValueError("Персонаж не относится к выбранному сезону")
    return character


def _character_speaker_labels(session: Session, season_id: int, character_id: int) -> dict[int, set[str]]:
    rows = session.execute(
        select(SpeakerIdentity.episode_id, SpeakerIdentity.source_label)
        .join(Episode, Episode.id == SpeakerIdentity.episode_id)
        .where(Episode.season_id == season_id)
        .where(SpeakerIdentity.character_id == character_id)
    ).all()
    result: dict[int, set[str]] = {}
    for episode_id, label in rows:
        result.setdefault(episode_id, set()).add(label)
    return result


def _candidate_has_speaker(session: Session, candidate: ClipCandidate, labels: set[str]) -> bool:
    if not labels:
        return False
    return session.scalar(
        select(TranscriptSegment.id)
        .where(TranscriptSegment.episode_id == candidate.episode_id)
        .where(TranscriptSegment.speaker_label.in_(labels))
        .where(TranscriptSegment.end_time >= candidate.start_time)
        .where(TranscriptSegment.start_time <= candidate.end_time)
        .limit(1)
    ) is not None


def _terms(prompt: str) -> list[str]:
    terms = [item.strip(" ,.!?;:()[]{}«»\"'").lower() for item in prompt.split()]
    return [item for item in terms if len(item) >= 4][:12]


def _validated_segment_range(
    session: Session,
    episode_id: int,
    start: float,
    end: float,
) -> tuple[float, float]:
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise ValueError("Серия сегмента не найдена")
    crossing_start = session.scalar(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode_id)
        .where(TranscriptSegment.start_time + 0.05 < start)
        .where(TranscriptSegment.end_time - 0.05 > start)
        .order_by(TranscriptSegment.start_time)
    )
    crossing_end = session.scalar(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode_id)
        .where(TranscriptSegment.start_time + 0.05 < end)
        .where(TranscriptSegment.end_time - 0.05 > end)
        .order_by(TranscriptSegment.start_time)
    )
    if crossing_start is not None:
        start = crossing_start.start_time
    if crossing_end is not None:
        end = crossing_end.end_time
    if start < 0 or end <= start:
        raise ValueError("Конец сегмента должен быть позже начала")
    if episode.duration_seconds is not None and end > episode.duration_seconds + 0.05:
        raise ValueError("Конец сегмента выходит за длительность серии")
    return round(start, 3), round(end, 3)


def _candidate_similarity(left: ClipCandidate, right: ClipCandidate) -> float:
    left_text = " ".join([left.title, left.description, left.continuity_note or ""])
    right_text = " ".join([right.title, right.description, right.continuity_note or ""])
    return semantic_similarity(left_text, right_text)


def _arc_title(request: StoryArcPlanRequest, season: Season, character: Character | None) -> str:
    if request.title and request.title.strip():
        return request.title.strip()
    if character is not None:
        return f"Арка персонажа: {character.name}"
    if request.prompt.strip():
        return request.prompt.strip()[:80]
    return f"Сюжетная арка: {season.title}"


def _default_arc_role(index: int, count: int) -> str:
    if index == 1:
        return "завязка"
    if index == count:
        return "итог"
    ratio = index / max(1, count)
    if ratio < 0.45:
        return "развитие"
    if ratio < 0.75:
        return "поворот"
    return "кульминация"


def _narration_plan(character: Character | None, chapters: list[dict]) -> list[dict]:
    if character is None:
        return []
    lines: list[dict] = []
    elapsed = 0.0
    for chapter in chapters:
        role = chapter["role"]
        title = chapter["title"]
        if role == "завязка":
            text = f"Сначала я столкнулся с моментом: {title}."
        elif role == "итог":
            text = f"Именно так закончилась эта часть моей истории: {title}."
        else:
            text = f"После этого для меня стало важным: {title}."
        lines.append(
            {
                "order": chapter["order"],
                "voice": character.name,
                "text": text,
                "start_time": round(elapsed + 0.35, 3),
            }
        )
        elapsed += float(chapter.get("duration") or 0.0)
    return lines


def _load_arc(session: Session, story_arc_id: int) -> StoryArc:
    arc = session.scalar(
        select(StoryArc)
        .options(selectinload(StoryArc.segments), selectinload(StoryArc.exports))
        .where(StoryArc.id == story_arc_id)
    )
    if arc is None:
        raise ValueError("Арка не найдена")
    return arc
