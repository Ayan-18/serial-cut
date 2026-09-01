from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJECT_ROOT / "data" / "models"

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


def model_catalog() -> list[ModelCatalogEntry]:
    return [_asr_entry(), _llm_entry(), _face_entry()]


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


def _download_verified(url: str, destination: Path, expected_hash: str, opener=urlopen) -> None:
    if destination.exists() and _file_sha256(destination) == expected_hash:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    request = Request(url, headers={"User-Agent": "SerialCuts local model installer"})
    try:
        with opener(request, timeout=120) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        actual = _file_sha256(temporary)
        if actual != expected_hash:
            raise RuntimeError(
                f"SHA-256 не совпал для {destination.name}: ожидалось {expected_hash}, получено {actual}"
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def install_model(key: str, *, confirm: bool, opener=urlopen) -> ModelCatalogEntry:
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
    face_dir = _face_dir()
    for name, url, expected_hash in FACE_MODELS:
        _download_verified(url, face_dir / name, expected_hash, opener=opener)
    return get_catalog_entry(key)
