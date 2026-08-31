from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen


MODELS = (
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


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(url: str, destination: Path, expected_hash: str) -> None:
    if destination.exists() and file_sha256(destination) == expected_hash:
        print(f"Already verified: {destination}", flush=True)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    request = Request(url, headers={"User-Agent": "SerialCuts local model installer"})
    try:
        with urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        actual_hash = file_sha256(temporary)
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"SHA-256 mismatch for {destination.name}: expected {expected_hash}, got {actual_hash}"
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    models_dir = Path(__file__).resolve().parent.parent / "data" / "models" / "face"
    for filename, url, expected_hash in MODELS:
        destination = models_dir / filename
        print(f"Downloading and verifying {filename}", flush=True)
        download_verified(url, destination, expected_hash)
    print("Local YuNet and SFace models are ready.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
