from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.application.model_install import FACE_MODELS, _download_verified, _face_dir  # noqa: E402


def main() -> int:
    face_dir = _face_dir()
    for filename, url, expected_hash in FACE_MODELS:
        print(f"Downloading and verifying {filename}", flush=True)
        _download_verified(url, face_dir / filename, expected_hash)
    print("Local YuNet and SFace models are ready.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
