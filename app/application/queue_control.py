from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import AppSetting


QUEUE_STATE_KEY = "queue_state"


def set_queue_paused(session: Session, paused: bool) -> str:
    state = "paused" if paused else "running"
    setting = session.get(AppSetting, QUEUE_STATE_KEY)
    if setting is None:
        session.add(AppSetting(key=QUEUE_STATE_KEY, value_json={"state": state}))
    else:
        setting.value_json = {"state": state}
    session.flush()
    return state


def get_queue_state(session: Session) -> str:
    setting = session.get(AppSetting, QUEUE_STATE_KEY)
    if setting is None:
        return "running"
    return str(setting.value_json.get("state", "running"))
