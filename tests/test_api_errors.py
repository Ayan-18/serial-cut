from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import BadRequestError, register_exception_handlers


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/bad-request")
    def bad_request():
        raise BadRequestError("Неверные границы клипа")

    @app.get("/unexpected")
    def unexpected():
        raise RuntimeError("internal ffmpeg command with private path")

    return app


def test_application_error_returns_readable_400():
    response = TestClient(_app()).get("/bad-request")

    assert response.status_code == 400
    assert response.json() == {"detail": "Неверные границы клипа"}


def test_unexpected_error_returns_generic_500_and_logs_traceback(caplog):
    client = TestClient(_app(), raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR, logger="app.api.errors"):
        response = client.get("/unexpected")

    assert response.status_code == 500
    assert response.json() == {"detail": "Внутренняя ошибка SerialCuts"}
    assert "private path" not in response.text
    assert "Unhandled API error" in caplog.text
    assert "internal ffmpeg command with private path" in caplog.text
