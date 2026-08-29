from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.application.review import review_candidate
from app.application.stage4 import render_candidate
from app.infrastructure.config import Settings
from app.models.entities import AppSetting


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
    elif action == "export":
        rendered = render_candidate(session, candidate_id, settings)
        result = CallbackResult(key, action, "rendered", f"Экспорт готов: {rendered.output_path}")
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

