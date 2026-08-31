from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.local_text import generate_local_text
from app.infrastructure.config import Settings
from app.models.entities import Season, StoryArc, VideoScript


@dataclass(frozen=True)
class VideoScriptRequest:
    season_id: int
    story_arc_id: int | None = None
    title: str | None = None
    prompt: str = ""
    style: str = "chronological"


def create_video_script(
    session: Session,
    request: VideoScriptRequest,
    settings: Settings | None = None,
) -> VideoScript:
    season = session.get(Season, request.season_id)
    if season is None:
        raise ValueError("Сезон не найден")
    arc = session.get(StoryArc, request.story_arc_id) if request.story_arc_id else None
    if request.story_arc_id and (arc is None or arc.season_id != season.id):
        raise ValueError("Арка не относится к выбранному сезону")
    title = (request.title or "").strip() or (f"Сценарий: {arc.title}" if arc else f"Сценарий: {season.title}")
    structure = _structure_for_arc(arc, request.prompt, request.style) if arc else _structure_for_season(season, request.prompt, request.style)
    template_text = _script_text(title, structure)
    generated_text = generate_local_text(settings, _script_prompt(season, arc, structure), 2200) if settings else None
    script = VideoScript(
        season_id=season.id,
        story_arc_id=arc.id if arc else None,
        title=title,
        prompt=request.prompt.strip(),
        style=request.style,
        script_text=generated_text or template_text,
        structure_json=structure,
        status="draft",
    )
    session.add(script)
    session.flush()
    return script


def list_video_scripts(session: Session, season_id: int | None = None) -> list[VideoScript]:
    query = select(VideoScript).order_by(VideoScript.updated_at.desc(), VideoScript.id.desc())
    if season_id is not None:
        query = query.where(VideoScript.season_id == season_id)
    return list(session.scalars(query).all())


def update_video_script(session: Session, script_id: int, title: str | None, script_text: str | None, status: str | None) -> VideoScript:
    script = session.get(VideoScript, script_id)
    if script is None:
        raise ValueError("Сценарий не найден")
    if title is not None and title.strip():
        script.title = title.strip()
    if script_text is not None:
        script.script_text = script_text.strip()
    if status is not None:
        script.status = status
    session.flush()
    return script


def _structure_for_arc(arc: StoryArc, prompt: str, style: str) -> dict:
    chapters = list((arc.plan_json or {}).get("chapters", []))
    beats = [
        {
            "order": item.get("order", index),
            "title": item.get("title", "Фрагмент"),
            "episode": item.get("episode", ""),
            "role": item.get("role") or "часть",
            "voiceover": _voiceover_line(item.get("role") or "часть", item.get("title", "фрагмент")),
        }
        for index, item in enumerate(chapters, start=1)
    ]
    return {
        "source": "story_arc",
        "story_arc_id": arc.id,
        "prompt": prompt.strip(),
        "style": style,
        "beats": beats,
        "cta": "Продолжение можно собрать из следующих частей арки.",
    }


def _structure_for_season(season: Season, prompt: str, style: str) -> dict:
    return {
        "source": "season",
        "season_id": season.id,
        "prompt": prompt.strip(),
        "style": style,
        "beats": [
            {
                "order": 1,
                "title": "Вступление",
                "episode": "",
                "role": "hook",
                "voiceover": f"Это история сезона «{season.title}».",
            }
        ],
        "cta": "Добавьте StoryArc, чтобы сценарий получил точные фрагменты.",
    }


def _script_text(title: str, structure: dict) -> str:
    lines = [title, "", "Хук:", _hook_line(structure), "", "Монтаж:"]
    for beat in structure.get("beats", []):
        episode = f" ({beat['episode']})" if beat.get("episode") else ""
        lines.append(f"{beat['order']}. {beat['title']}{episode}: {beat['voiceover']}")
    lines.extend(["", "Финал:", structure.get("cta", "")])
    return "\n".join(lines).strip()


def _hook_line(structure: dict) -> str:
    prompt = structure.get("prompt") or ""
    if prompt:
        return f"Сразу показать главный вопрос: {prompt}."
    if structure.get("beats"):
        return f"Начать с сильного кадра: {structure['beats'][0]['title']}."
    return "Начать с самого понятного и эмоционального момента."


def _voiceover_line(role: str, title: str) -> str:
    if role == "завязка":
        return f"Здесь начинается линия: {title}."
    if role == "итог":
        return f"Этим моментом история закрывается: {title}."
    if role == "кульминация":
        return f"Напряжение выходит на максимум в моменте: {title}."
    return f"Дальше история двигается через момент: {title}."


def _script_prompt(season: Season, arc: StoryArc | None, structure: dict) -> str:
    beats = "\n".join(
        f"{item.get('order')}. {item.get('episode', '')} — {item.get('title', '')} "
        f"[{item.get('role', '')}]"
        for item in structure.get("beats", [])
    )
    return (
        "Составь готовый сценарий монтажа по структуре ниже. Добавь сильный хук, короткие "
        "связки между частями и финал. Не пересказывай факты, которых нет в названиях частей. "
        "Отдельно пометь строки ЗАКАДРОВЫЙ ТЕКСТ и МОНТАЖ.\n\n"
        f"Сезон: {season.title}\nКонтекст сезона: {season.story_context or 'не задан'}\n"
        f"Арка: {arc.title if arc else 'весь сезон'}\n"
        f"Пожелание: {structure.get('prompt') or 'хронологично и понятно'}\n"
        f"Части:\n{beats}"
    )
