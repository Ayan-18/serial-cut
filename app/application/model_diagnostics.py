from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.infrastructure.config import Settings


@dataclass(frozen=True)
class ModelDiagnostics:
    asr_adapter: str
    asr_ready: bool
    llm_adapter: str
    llm_ready: bool
    llm_url: str
    details: list[str]


def check_models(settings: Settings) -> ModelDiagnostics:
    details: list[str] = []
    if settings.asr_adapter == "stub":
        asr_ready = True
        details.append("ASR работает в тестовом режиме")
    else:
        asr_ready = find_spec("faster_whisper") is not None
        details.append("faster-whisper установлен" if asr_ready else "Не найден пакет faster-whisper")

    if settings.llm_adapter == "stub":
        llm_ready = True
        details.append("LLM работает в тестовом режиме")
    else:
        llm_ready = _llm_health(settings.llm_base_url)
        details.append("Локальный LLM отвечает" if llm_ready else "Локальный LLM не отвечает")

    return ModelDiagnostics(
        asr_adapter=settings.asr_adapter,
        asr_ready=asr_ready,
        llm_adapter=settings.llm_adapter,
        llm_ready=llm_ready,
        llm_url=settings.llm_base_url,
        details=details,
    )


def _llm_health(base_url: str) -> bool:
    request = Request(f"{base_url.rstrip('/')}/health", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=2) as response:
            if response.status >= 400:
                return False
            payload = response.read(8192)
            if not payload:
                return True
            json.loads(payload)
            return True
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False
