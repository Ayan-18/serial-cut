from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import PublishingPlan, Season, StoryArc, StoryArcExport


@dataclass(frozen=True)
class PublishingPlanRequest:
    season_id: int
    story_arc_id: int | None = None
    story_arc_export_id: int | None = None
    platform: str = "youtube_shorts"
    scheduled_for: datetime | None = None


def create_publishing_plan(session: Session, request: PublishingPlanRequest) -> PublishingPlan:
    season = session.get(Season, request.season_id)
    if season is None:
        raise ValueError("Сезон не найден")
    arc = session.get(StoryArc, request.story_arc_id) if request.story_arc_id else None
    if request.story_arc_id and (arc is None or arc.season_id != season.id):
        raise ValueError("Арка не относится к сезону")
    export = session.get(StoryArcExport, request.story_arc_export_id) if request.story_arc_export_id else None
    if request.story_arc_export_id and export is None:
        raise ValueError("Экспорт StoryArc не найден")
    if export is not None and arc is None:
        arc = session.get(StoryArc, export.story_arc_id)
    if export is not None and arc is not None and export.story_arc_id != arc.id:
        raise ValueError("Экспорт не относится к выбранной арке")
    title = _title(season, arc)
    plan = PublishingPlan(
        season_id=season.id,
        story_arc_id=arc.id if arc else None,
        story_arc_export_id=export.id if export else None,
        platform=request.platform,
        title=title,
        description=_description(season, arc),
        hashtags_json=_hashtags(season, arc),
        scheduled_for=request.scheduled_for,
        status="draft",
    )
    session.add(plan)
    session.flush()
    return plan


def list_publishing_plans(session: Session, season_id: int | None = None) -> list[PublishingPlan]:
    query = select(PublishingPlan).order_by(PublishingPlan.created_at.desc(), PublishingPlan.id.desc())
    if season_id is not None:
        query = query.where(PublishingPlan.season_id == season_id)
    return list(session.scalars(query).all())


def update_publishing_plan(
    session: Session,
    plan_id: int,
    title: str | None = None,
    description: str | None = None,
    hashtags: list[str] | None = None,
    scheduled_for: datetime | None = None,
    status: str | None = None,
) -> PublishingPlan:
    plan = session.get(PublishingPlan, plan_id)
    if plan is None:
        raise ValueError("План публикации не найден")
    if title is not None and title.strip():
        plan.title = title.strip()
    if description is not None:
        plan.description = description.strip()
    if hashtags is not None:
        plan.hashtags_json = [_normalize_hashtag(item) for item in hashtags if item.strip()]
    if scheduled_for is not None:
        plan.scheduled_for = scheduled_for
    if status is not None:
        plan.status = status
    session.flush()
    return plan


def _title(season: Season, arc: StoryArc | None) -> str:
    if arc is not None:
        return arc.title[:95]
    return f"Лучшие моменты: {season.title}"[:95]


def _description(season: Season, arc: StoryArc | None) -> str:
    if arc is None:
        return f"Нарезка лучших моментов из сезона «{season.title}»."
    duration = round(arc.total_duration_seconds)
    return f"{arc.title}\n\nСезон: {season.title}\nФормат: {arc.output_format}\nДлительность: {duration} сек."


def _hashtags(season: Season, arc: StoryArc | None) -> list[str]:
    base = [_normalize_hashtag(season.title), "#serialcuts", "#shorts"]
    if arc is not None:
        base.append(_normalize_hashtag(arc.title))
        if arc.target_character_id:
            target = (arc.plan_json or {}).get("target_character")
            if isinstance(target, str) and target:
                base.append(_normalize_hashtag(target))
    return list(dict.fromkeys(item for item in base if item != "#"))


def _normalize_hashtag(value: str) -> str:
    compact = "".join(ch for ch in value if ch.isalnum() or ch in "_").strip("_")
    return f"#{compact.lower()}" if compact else "#"
