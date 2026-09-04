from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJECT_ROOT / "data" / "models"

# Progress bytes reported by an in-flight download. delta = bytes just written,
# content_length = Content-Length of the current file (0 if the server omits it).
ProgressCallback = Callable[[int, int], None]

FACE_MODELS = (
    (
        "face_detection_yunet_2026may.onnx",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2026may.onnx",
        "ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0",
    ),
    (
        "face_recognition_sface_2021dec.onnx",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
)

# Silero has no stable per-file SHA publication, so this is verified by attempting
# a torch.package load after download instead of a pinned hash.
TTS_MODEL_URL = "https://models.silero.ai/models/tts/ru/v4_ru.pt"
TTS_MODEL_NAME = "v4_ru.pt"
TTS_MODEL_MIN_BYTES = 20 * 1024 * 1024
TTS_MODEL_MAX_BYTES = 400 * 1024 * 1024


@dataclass(frozen=True)
class ModelCatalogEntry:
    key: str
    title: str
    purpose: str
    approx_size_mb: int
    target_dir: str
    installed: bool
    files_present: list[str]
    files_missing: list[str]
    installable_in_app: bool
    install_command: str


def _face_dir() -> Path:
    return MODELS_DIR / "face"


def _face_entry() -> ModelCatalogEntry:
    face_dir = _face_dir()
    present = [name for name, _, _ in FACE_MODELS if (face_dir / name).exists()]
    missing = [name for name, _, _ in FACE_MODELS if not (face_dir / name).exists()]
    return ModelCatalogEntry(
        key="face",
        title="YuNet + SFace (распознавание лиц)",
        purpose="Автокадрирование по активному говорящему и привязка лиц к персонажам.",
        approx_size_mb=39,
        target_dir=str(face_dir),
        installed=not missing,
        files_present=present,
        files_missing=missing,
        installable_in_app=True,
        install_command="powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\install_identity_models.ps1",
    )


def _dir_has_files(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def _asr_entry() -> ModelCatalogEntry:
    asr_dir = MODELS_DIR / "faster-whisper-small"
    installed = _dir_has_files(asr_dir)
    return ModelCatalogEntry(
        key="asr",
        title="faster-whisper small (расшифровка речи)",
        purpose="Локальное распознавание русской речи с таймкодами слов.",
        approx_size_mb=480,
        target_dir=str(asr_dir),
        installed=installed,
        files_present=[asr_dir.name] if installed else [],
        files_missing=[] if installed else [asr_dir.name],
        installable_in_app=False,
        install_command="powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\install_models.ps1",
    )


def _llm_entry() -> ModelCatalogEntry:
    llm_dir = MODELS_DIR / "qwen3-4b"
    installed = _dir_has_files(llm_dir)
    return ModelCatalogEntry(
        key="llm",
        title="Qwen3-4B GGUF Q4_K_M (поиск моментов)",
        purpose="Локальная модель для карты серии, кандидатов и сценариев.",
        approx_size_mb=2500,
        target_dir=str(llm_dir),
        installed=installed,
        files_present=[llm_dir.name] if installed else [],
        files_missing=[] if installed else [llm_dir.name],
        installable_in_app=False,
        install_command="powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\install_models.ps1",
    )


def _tts_dir() -> Path:
    return MODELS_DIR / "tts"


def _tts_entry() -> ModelCatalogEntry:
    model_path = _tts_dir() / TTS_MODEL_NAME
    installed = model_path.exists()
    return ModelCatalogEntry(
        key="tts",
        title="Silero v4_ru (озвучка StoryArc)",
        purpose="Живой русский голос диктора для закадрового текста арок (не имитация актёра).",
        approx_size_mb=60,
        target_dir=str(_tts_dir()),
        installed=installed,
        files_present=[TTS_MODEL_NAME] if installed else [],
        files_missing=[] if installed else [TTS_MODEL_NAME],
        installable_in_app=True,
        install_command="powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\install_tts_model.ps1",
    )


def model_catalog() -> list[ModelCatalogEntry]:
    return [_asr_entry(), _llm_entry(), _face_entry(), _tts_entry()]


def get_catalog_entry(key: str) -> ModelCatalogEntry:
    for entry in model_catalog():
        if entry.key == key:
            return entry
    raise ValueError(f"Неизвестная модель: {key}")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_length(response: object) -> int:
    headers = getattr(response, "headers", None)
    try:
        return int(headers.get("Content-Length", 0)) if headers is not None else 0
    except (TypeError, ValueError):
        return 0


def _download_verified(
    url: str, destination: Path, expected_hash: str, opener=None, on_progress: ProgressCallback | None = None
) -> None:
    opener = opener or urlopen
    if destination.exists() and _file_sha256(destination) == expected_hash:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    request = Request(url, headers={"User-Agent": "SerialCuts local model installer"})
    try:
        with opener(request, timeout=120) as response, temporary.open("wb") as output:
            total = _content_length(response)
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                if on_progress is not None:
                    on_progress(len(chunk), total)
        actual = _file_sha256(temporary)
        if actual != expected_hash:
            raise RuntimeError(
                f"SHA-256 не совпал для {destination.name}: ожидалось {expected_hash}, получено {actual}"
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _verify_silero_model(path: Path) -> None:
    size = path.stat().st_size if path.exists() else 0
    if not TTS_MODEL_MIN_BYTES <= size <= TTS_MODEL_MAX_BYTES:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"Скачанный файл Silero имеет неожиданный размер ({size} байт)")
    try:
        import torch
    except ImportError:
        return  # torch not installed yet; size check is the best we can do
    try:
        torch.package.PackageImporter(str(path)).load_pickle("tts_models", "model")
    except Exception as exc:  # noqa: BLE001 - any load failure means a bad file
        path.unlink(missing_ok=True)
        raise RuntimeError(f"Скачанная модель Silero не загружается: {exc}") from exc


def _download_silero(*, opener=None, on_progress: ProgressCallback | None = None) -> None:
    opener = opener or urlopen
    destination = _tts_dir() / TTS_MODEL_NAME
    if destination.exists():
        _verify_silero_model(destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    request = Request(TTS_MODEL_URL, headers={"User-Agent": "SerialCuts local model installer"})
    try:
        with opener(request, timeout=300) as response, temporary.open("wb") as output:
            total = _content_length(response)
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                if on_progress is not None:
                    on_progress(len(chunk), total)
        _verify_silero_model(temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def install_model(
    key: str, *, confirm: bool, opener=None, on_progress: ProgressCallback | None = None
) -> ModelCatalogEntry:
    entry = get_catalog_entry(key)
    if not entry.installable_in_app:
        raise ValueError(
            f"{entry.title} весит ~{entry.approx_size_mb} МБ и ставится командой: {entry.install_command}"
        )
    if not confirm:
        raise ValueError(
            f"Подтвердите загрузку ~{entry.approx_size_mb} МБ в {entry.target_dir} (confirm=true)"
        )
    if entry.installed:
        return entry
    if key == "tts":
        _download_silero(opener=opener, on_progress=on_progress)
        return get_catalog_entry(key)
    face_dir = _face_dir()
    for name, url, expected_hash in FACE_MODELS:
        _download_verified(url, face_dir / name, expected_hash, opener=opener, on_progress=on_progress)
    return get_catalog_entry(key)


@dataclass
class ModelInstallProgress:
    key: str
    status: str  # "idle" | "running" | "done" | "error"
    received_bytes: int = 0
    total_bytes: int = 0
    detail: str = ""


_INSTALL_LOCK = threading.Lock()
_INSTALL_PROGRESS: dict[str, ModelInstallProgress] = {}


def get_model_install_progress(key: str) -> ModelInstallProgress:
    with _INSTALL_LOCK:
        current = _INSTALL_PROGRESS.get(key)
        return (
            ModelInstallProgress(**vars(current)) if current is not None else ModelInstallProgress(key, "idle")
        )


def start_model_install(key: str, *, confirm: bool) -> ModelInstallProgress:
    """Kick a model download onto a daemon thread and track its byte progress."""
    entry = get_catalog_entry(key)  # raises ValueError for an unknown key
    with _INSTALL_LOCK:
        if any(p.status == "running" for p in _INSTALL_PROGRESS.values()):
            raise RuntimeError("Уже идёт установка другой модели — дождитесь её завершения")
        if entry.installed:
            return ModelInstallProgress(key, "done", detail="Уже установлено")
        state = ModelInstallProgress(key, "running", detail=entry.title)
        _INSTALL_PROGRESS[key] = state

    received = {"n": 0, "total": 0}

    def on_progress(delta: int, content_length: int) -> None:
        received["n"] += delta
        received["total"] = max(received["total"], content_length, received["n"])
        with _INSTALL_LOCK:
            live = _INSTALL_PROGRESS.get(key)
            if live is not None:
                live.received_bytes = received["n"]
                live.total_bytes = received["total"]

    def worker() -> None:
        try:
            install_model(key, confirm=confirm, on_progress=on_progress)
            _finish(key, "done", "Готово")
        except Exception as exc:  # noqa: BLE001 - surfaced to the panel
            logger.warning("Model install failed: key=%s", key, exc_info=True)
            _finish(key, "error", str(exc))

    threading.Thread(target=worker, name=f"model-install-{key}", daemon=True).start()
    return ModelInstallProgress(**vars(state))


def _finish(key: str, status: str, detail: str) -> None:
    with _INSTALL_LOCK:
        live = _INSTALL_PROGRESS.get(key)
        if live is not None:
            live.status = status
            live.detail = detail
