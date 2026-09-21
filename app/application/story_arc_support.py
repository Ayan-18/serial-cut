from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.application.story_arc_ranking import StoryArcBuildItem, StoryArcPlanRequest
from app.models.entities import Character, Episode, Season, StoryArc, StoryArcSegment, TranscriptSegment


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
