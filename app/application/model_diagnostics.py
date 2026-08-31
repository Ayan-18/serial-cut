from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
import json
from pathlib import Path
from time import monotonic
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.infrastructure.config import Settings


@dataclass(frozen=True)
class ModelDiagnostics:
    asr_adapter: str
    asr_ready: bool
    asr_model: str
    asr_device: str
    asr_compute_type: str
    asr_package_installed: bool
    asr_local_model_path: str | None
    asr_local_model_exists: bool
    llm_adapter: str
    llm_ready: bool
    llm_url: str
    llm_model_hint: str
    llm_latency_ms: int | None
    face_ready: bool
    face_model: str
    face_detector_path: str
    face_recognizer_path: str
    face_detector_exists: bool
    face_recognizer_exists: bool
    details: list[str]
    recommendations: list[str]


def check_models(settings: Settings) -> ModelDiagnostics:
    details: list[str] = []
    recommendations: list[str] = []
    asr_package_installed = find_spec("faster_whisper") is not None
    local_model_path = _local_model_path(settings.asr_model_name)
    asr_local_model_exists = bool(local_model_path and local_model_path.exists())
    if settings.asr_adapter == "stub":
        asr_ready = True
        details.append("ASR работает в тестовом режиме")
    else:
        asr_ready = asr_package_installed
        details.append("faster-whisper установлен" if asr_ready else "Не найден пакет faster-whisper")
        if not asr_package_installed:
            recommendations.append("Установите faster-whisper в .venv основного компьютера")
        if local_model_path and not asr_local_model_exists:
            recommendations.append(f"Проверьте локальную папку Whisper: {local_model_path}")

    if settings.llm_adapter == "stub":
        llm_ready = True
        llm_latency_ms = None
        details.append("LLM работает в тестовом режиме")
    else:
        llm_ready, llm_latency_ms = _llm_health(settings.llm_base_url)
        details.append(
            f"Локальный LLM отвечает за {llm_latency_ms} мс"
            if llm_ready and llm_latency_ms is not None
            else "Локальный LLM не отвечает"
        )
        if not llm_ready:
            recommendations.append("Запустите llama.cpp server на адресе из настроек LLM")

    face_detector_exists = settings.face_detector_model.exists()
    face_recognizer_exists = settings.face_recognizer_model.exists()
    face_ready = face_detector_exists and face_recognizer_exists
    details.append(
        "YuNet и SFace готовы"
        if face_ready
        else "YuNet/SFace не установлены — доступен резервный поиск лиц"
    )
    if not face_ready:
        recommendations.append("Положите YuNet и SFace ONNX-модели в data/models/face для лучшего автокадрирования")

    return ModelDiagnostics(
        asr_adapter=settings.asr_adapter,
        asr_ready=asr_ready,
        asr_model=settings.asr_model_name,
        asr_device=settings.asr_device,
        asr_compute_type=settings.asr_compute_type,
        asr_package_installed=asr_package_installed,
        asr_local_model_path=str(local_model_path) if local_model_path else None,
        asr_local_model_exists=asr_local_model_exists,
        llm_adapter=settings.llm_adapter,
        llm_ready=llm_ready,
        llm_url=settings.llm_base_url,
        llm_model_hint=settings.llm_model_hint,
        llm_latency_ms=llm_latency_ms,
        face_ready=face_ready,
        face_model="YuNet + SFace" if face_ready else "Haar + DCT",
        face_detector_path=str(settings.face_detector_model),
        face_recognizer_path=str(settings.face_recognizer_model),
        face_detector_exists=face_detector_exists,
        face_recognizer_exists=face_recognizer_exists,
        details=details,
        recommendations=recommendations,
    )


def _llm_health(base_url: str) -> tuple[bool, int | None]:
    request = Request(f"{base_url.rstrip('/')}/health", headers={"Accept": "application/json"})
    try:
        started = monotonic()
        with urlopen(request, timeout=2) as response:
            if response.status >= 400:
                return False, None
            payload = response.read(8192)
            latency_ms = round((monotonic() - started) * 1000)
            if not payload:
                return True, latency_ms
            json.loads(payload)
            return True, latency_ms
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False, None


def _local_model_path(model_name: str) -> Path | None:
    path = Path(model_name)
    if path.is_absolute() or path.parts[:1] in [(".",), ("..",)] or "\\" in model_name or "/" in model_name:
        return path
    return None
