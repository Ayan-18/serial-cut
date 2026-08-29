from __future__ import annotations

from app.application.queue_control import get_queue_state, set_queue_paused


def test_queue_control_persists_pause_state(session):
    assert get_queue_state(session) == "running"
    assert set_queue_paused(session, True) == "paused"
    assert get_queue_state(session) == "paused"
    assert set_queue_paused(session, False) == "running"
    assert get_queue_state(session) == "running"

