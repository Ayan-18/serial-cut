from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.queue_routes import build_queue_data
from app.infrastructure.database import session_scope

router = APIRouter(prefix="/api", tags=["events"])

_POLL_SECONDS = 1.5
_HEARTBEAT_SECONDS = 20.0


def _queue_payload() -> str:
    with session_scope() as session:
        return build_queue_data(session).model_dump_json()


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Server-sent stream of queue/job changes — replaces the 2.5 s frontend poll."""

    async def stream() -> AsyncIterator[str]:
        last: str | None = None
        idle = 0.0
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected():
                return
            payload = await asyncio.to_thread(_queue_payload)
            if payload != last:
                last = payload
                idle = 0.0
                yield f"event: queue\ndata: {payload}\n\n"
            else:
                idle += _POLL_SECONDS
                if idle >= _HEARTBEAT_SECONDS:
                    idle = 0.0
                    yield ": ping\n\n"
            await asyncio.sleep(_POLL_SECONDS)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
