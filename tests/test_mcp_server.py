from __future__ import annotations

import asyncio

import httpx
import pytest

mcp_server = pytest.importorskip("app.mcp_server")


def test_every_tool_is_registered_and_described():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert {"health", "list_seasons", "analyze_episode", "render_candidate", "create_story_arc"} <= names
    assert all(tool.description for tool in tools)


def test_api_raises_a_clear_error_when_the_app_is_down(monkeypatch):
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("refused", request=httpx.Request("GET", "http://127.0.0.1:8090/"))

    monkeypatch.setattr(mcp_server.httpx.Client, "request", refuse, raising=False)
    with pytest.raises(RuntimeError, match="SerialCuts не запущен"):
        mcp_server._api("GET", "/api/health")


def test_api_surfaces_the_http_detail(monkeypatch):
    class _Resp:
        status_code = 404
        content = b'{"detail": "..."}'
        text = '{"detail": "Серия не найдена"}'

        def json(self):
            return {"detail": "Серия не найдена"}

    monkeypatch.setattr(mcp_server.httpx.Client, "request", lambda *a, **k: _Resp(), raising=False)
    with pytest.raises(RuntimeError, match="Серия не найдена"):
        mcp_server._api("GET", "/api/episodes/999/candidates")
