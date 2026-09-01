from __future__ import annotations

from ipaddress import ip_address

from starlette.types import ASGIApp, Receive, Scope, Send


class LoopbackOnlyMiddleware:
    """Deny remote HTTP clients even if uvicorn is accidentally bound to a LAN address."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"} and not _is_loopback_client(scope):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008, "reason": "Loopback only"})
                return
            body = "SerialCuts доступен только с этого компьютера".encode("utf-8")
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
            return
        await self.app(scope, receive, send)


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
