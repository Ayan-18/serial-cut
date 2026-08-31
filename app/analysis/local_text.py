from __future__ import annotations

import httpx

from app.infrastructure.config import Settings


def generate_local_text(
    settings: Settings,
    prompt: str,
    max_tokens: int = 1800,
) -> str | None:
    if settings.llm_adapter == "stub":
        return None
    try:
        response = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/v1/chat/completions",
            json={
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Ты локальный монтажный редактор. Пиши по-русски, конкретно, "
                            "не выдумывай события вне предоставленного материала."
                        ),
                    },
                    {"role": "user", "content": f"/no_think\n{prompt}"},
                ],
                "temperature": 0.25,
                "top_p": 0.85,
                "max_tokens": max_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    try:
        choices = payload.get("choices") or []
        value = str((choices[0].get("message") or {}).get("content") or "") if choices else ""
    except (AttributeError, IndexError, TypeError):
        return None
    value = value.strip()
    if value.startswith("```"):
        value = value.strip("`").removeprefix("text").strip()
    return value or None
