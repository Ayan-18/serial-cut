from __future__ import annotations

import hmac
from ipaddress import ip_address
from secrets import token_urlsafe

from starlette.types import ASGIApp, Receive, Scope, Send


LOCAL_API_TOKEN_HEADER = b"x-serialcuts-token"
_LOCAL_API_TOKEN = token_urlsafe(32)
_SAFE_METHODS = {b"GET", b"HEAD", b"OPTIONS"}
# Only these hostnames may appear in the Host header. Blocks DNS-rebinding: an
# attacker page whose domain resolves to 127.0.0.1 still sends its own host here.
_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "testserver", "testclient"}


class LoopbackOnlyMiddleware:
    """Deny remote clients and require a same-origin token for unsafe local actions."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"} and not _is_loopback_client(scope):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008, "reason": "Loopback only"})
                return
            await _send_forbidden(send, "SerialCuts доступен только с этого компьютера")
            return
        if scope["type"] in {"http", "websocket"} and not _has_allowed_host(scope):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008, "reason": "Host not allowed"})
                return
            await _send_forbidden(send, "Недопустимый Host — SerialCuts принимает только локальные адреса")
            return
        if scope["type"] == "http" and _requires_local_api_token(scope) and not _has_valid_local_api_token(scope):
            await _send_forbidden(send, "Нужен локальный SerialCuts API token")
            return
        await self.app(scope, receive, send)


def local_api_token() -> str:
    return _LOCAL_API_TOKEN


def _is_loopback_client(scope: Scope) -> bool:
    client = scope.get("client")
    if client is None:
        return True
    host = str(client[0]).strip().strip("[]").casefold()
    if host in {"localhost", "testclient"}:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _has_allowed_host(scope: Scope) -> bool:
    header = b""
    for name, value in scope.get("headers") or []:
        if bytes(name).lower() == b"host":
            header = bytes(value)
            break
    if not header:
        # Non-browser clients (HTTP/1.0, some tools) may omit Host; the loopback
        # client check already covers them.
        return True
    raw = header.decode("latin-1", errors="ignore").strip().casefold()
    if raw.startswith("["):  # [::1]:8090
        hostname = raw[1 : raw.find("]")] if "]" in raw else raw[1:]
    else:
        hostname = raw.rsplit(":", 1)[0] if raw.rsplit(":", 1)[-1].isdigit() else raw
    if hostname in _ALLOWED_HOSTS:
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _requires_local_api_token(scope: Scope) -> bool:
    if _is_test_client(scope):
        return False
    method = str(scope.get("method") or "GET").encode("ascii", errors="ignore").upper()
    return method not in _SAFE_METHODS


def _has_valid_local_api_token(scope: Scope) -> bool:
    provided = b""
    for name, value in scope.get("headers") or []:
        if bytes(name).lower() == LOCAL_API_TOKEN_HEADER:
            provided = bytes(value)
            break
    return hmac.compare_digest(provided.decode("utf-8", errors="ignore"), _LOCAL_API_TOKEN)


def _is_test_client(scope: Scope) -> bool:
    client = scope.get("client")
    return bool(client and str(client[0]).casefold() == "testclient")


async def _send_forbidden(send: Send, message: str) -> None:
    body = message.encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
