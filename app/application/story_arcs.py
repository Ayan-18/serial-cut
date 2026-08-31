from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Character, ClipCandidate, Episode, Season, SpeakerIdentity, StoryArc, StoryArcSegment, TranscriptSegment


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


def create_story_arc_plan(session: Session, request: StoryArcPlanRequest) -> StoryArc:
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
    arc.plan_json = _plan_json(arc, season, character, selected)
    session.flush()
    return _load_arc(session, arc.id)


def list_story_arcs(session: Session, season_id: int | None = None) -> list[StoryArc]:
    query = select(StoryArc).options(selectinload(StoryArc.segments)).order_by(StoryArc.updated_at.desc(), StoryArc.id.desc())
    if season_id is not None:
        query = query.where(StoryArc.season_id == season_id)
    return list(session.scalars(query).all())


def get_story_arc(session: Session, story_arc_id: int) -> StoryArc:
    return _load_arc(session, story_arc_id)


def delete_story_arc(session: Session, story_arc_id: int) -> None:
    arc = session.get(StoryArc, story_arc_id)
    if arc is None:
        raise ValueError("Арка не найдена")
    session.delete(arc)
    session.flush()


def update_story_arc(session: Session, story_arc_id: int, patch: StoryArcUpdate) -> StoryArc:
    arc = _load_arc(session, story_arc_id)
    if patch.title is not None and patch.title.strip():
        arc.title = patch.title.strip()
    if patch.prompt is not None:
        arc.prompt = patch.prompt.strip()
    if patch.output_format is not None:
        arc.output_format = patch.output_format
    if patch.status is not None:
        arc.status = patch.status
    if patch.narration is not None:
        plan = dict(arc.plan_json or {})
        plan["narration"] = patch.narration
        arc.plan_json = plan
    _refresh_arc_plan_from_segments(session, arc)
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
    if segment.end_time <= segment.start_time:
        raise ValueError("Конец сегмента должен быть позже начала")
    if patch.title is not None and patch.title.strip():
        segment.title = patch.title.strip()
    if patch.note is not None:
        segment.note = patch.note.strip()
    if patch.role is not None:
        segment.role = patch.role.strip() or None
    if target_order is not None:
        _move_segment(arc, segment, target_order)
    else:
        _normalize_segment_order(arc)
    _refresh_arc_plan_from_segments(session, arc)
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
    _refresh_arc_plan_from_segments(session, arc)
    session.flush()
    return _load_arc(session, arc.id)


def add_candidate_to_story_arc(session: Session, story_arc_id: int, candidate_id: int) -> StoryArc:
    arc = _load_arc(session, story_arc_id)
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError("Кандидат не найден")
    episode = session.get(Episode, candidate.episode_id)
    if episode is None or episode.season_id != arc.season_id:
        raise ValueError("Кандидат должен быть из того же сезона")
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
    )
    session.add(segment)
    session.flush()
    arc = _load_arc(session, arc.id)
    _refresh_arc_plan_from_segments(session, arc)
    session.flush()
    return _load_arc(session, arc.id)


def rebuild_story_arc_plan(session: Session, story_arc_id: int) -> StoryArc:
    arc = _load_arc(session, story_arc_id)
    request = StoryArcPlanRequest(
        season_id=arc.season_id,
        title=arc.title,
        prompt=arc.prompt,
        arc_type=arc.arc_type,
        output_format=arc.output_format,
        target_character_id=arc.target_character_id,
        max_segments=max(1, len(arc.segments)),
        max_duration_seconds=max(15, round(arc.total_duration_seconds)),
    )
    character = _target_character(session, request.target_character_id, arc.season_id)
    candidates = _rank_candidates(session, arc.season_id, request.prompt, character)
    selected = _select_arc_items(candidates, request.max_segments, request.max_duration_seconds)
    if not selected:
        raise ValueError("Не удалось пересобрать арку")
    _replace_segments(session, arc, selected)
    arc.total_duration_seconds = round(sum(item.candidate.end_time - item.candidate.start_time for item in selected), 3)
    arc.plan_json = _plan_json(arc, arc.season, character, selected)
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
            if matches:
                score += min(20, matches * 5)
                reasons.append(f"совпадений с запросом: {matches}")
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
        items.append(StoryArcBuildItem(candidate, episode, score, ", ".join(reasons)))
    return sorted(items, key=lambda item: item.score, reverse=True)


def _select_arc_items(
    candidates: list[StoryArcBuildItem],
    max_segments: int,
    max_duration_seconds: int,
) -> list[StoryArcBuildItem]:
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
        selected.append(item)
        per_episode[item.episode.id] = per_episode.get(item.episode.id, 0) + 1
        total += duration
    return sorted(selected, key=lambda item: (item.episode.file_name, item.candidate.start_time))


def _replace_segments(session: Session, arc: StoryArc, items: list[StoryArcBuildItem]) -> None:
    session.execute(delete(StoryArcSegment).where(StoryArcSegment.story_arc_id == arc.id))
    for index, item in enumerate(items, start=1):
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
                role=candidate.story_role or _default_arc_role(index, len(items)),
            )
        )
    session.flush()


def _plan_json(
    arc: StoryArc,
    season: Season,
    character: Character | None,
    items: list[StoryArcBuildItem],
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
        "total_duration_seconds": round(sum(item["duration"] for item in chapters), 3),
        "chapters": chapters,
        "narration": _narration_plan(character, chapters),
        "next_step": "Проверьте порядок и границы, затем можно рендерить multi-source StoryArc.",
    }


def _refresh_arc_plan_from_segments(session: Session, arc: StoryArc) -> None:
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
        "narration": narration if narration is not None else _narration_plan(character, chapters),
    }


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
    for chapter in chapters:
        role = chapter["role"]
        title = chapter["title"]
        if role == "завязка":
            text = f"Сначала я столкнулся с моментом: {title}."
        elif role == "итог":
            text = f"Именно так закончилась эта часть моей истории: {title}."
        else:
            text = f"После этого для меня стало важным: {title}."
        lines.append({"order": chapter["order"], "voice": character.name, "text": text})
    return lines


def _load_arc(session: Session, story_arc_id: int) -> StoryArc:
    arc = session.scalar(
        select(StoryArc)
        .options(selectinload(StoryArc.segments))
        .where(StoryArc.id == story_arc_id)
    )
    if arc is None:
        raise ValueError("Арка не найдена")
    return arc
