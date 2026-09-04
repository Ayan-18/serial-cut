from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.application.review import review_candidate
from app.infrastructure.config import Settings
from app.models.entities import AppSetting
from app.workers.queue import enqueue_candidate_render


@dataclass(frozen=True)
class CallbackResult:
    idempotency_key: str
    action: str
    status: str
    message: str


def handle_candidate_callback(
    session: Session,
    settings: Settings,
    idempotency_key: str,
    action: str,
    candidate_id: int,
) -> CallbackResult:
    key = f"telegram_callback:{idempotency_key}"
    existing = session.get(AppSetting, key)
    if existing is not None:
        value = existing.value_json
        return CallbackResult(key, str(value["action"]), str(value["status"]), str(value["message"]))

    if action == "approve":
        reviewed = review_candidate(session, candidate_id, "approve")
        result = CallbackResult(key, action, reviewed.status, "Кандидат принят")
    elif action == "reject":
        reviewed = review_candidate(session, candidate_id, "reject")
        result = CallbackResult(key, action, reviewed.status, "Кандидат отклонён")
    elif action in {"render", "export"}:
        # Never render inside the bot's event loop — queue it and let the app
        # worker do the FFmpeg pass, then push the file back over Telegram.
        job = enqueue_candidate_render(session, candidate_id, {"include_subtitles": True})
        result = CallbackResult(
            key, "render", "queued", f"Рендер в очереди, задача №{job.id}. Пришлю файл, когда будет готово."
        )
    else:
        raise ValueError(f"Unknown Telegram callback action: {action}")

    session.add(
        AppSetting(
            key=key,
            value_json={
                "action": result.action,
                "status": result.status,
                "message": result.message,
                "candidate_id": candidate_id,
            },
        )
    )
    session.flush()
    return result


def is_user_allowed(user_id: int, allowed_user_ids: list[int]) -> bool:
    return user_id in set(allowed_user_ids)

