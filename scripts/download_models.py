from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download


ASR_REPO = "Systran/faster-whisper-small"
ASR_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
LLM_REPO = "ggml-org/Qwen3-4B-GGUF"
LLM_FILENAME = "Qwen3-4B-Q4_K_M.gguf"
LLM_SHA256 = "ab27b9bfa375a178d6cba48f3ad892b94b7739659dcc7aae8058ce0ffed6b328"


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    models_dir = project_root / "data" / "models"
    asr_dir = models_dir / "faster-whisper-small"
    llm_dir = models_dir / "qwen3-4b"
    models_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {ASR_REPO} to {asr_dir}", flush=True)
    snapshot_download(
        repo_id=ASR_REPO,
        revision=ASR_REVISION,
        local_dir=asr_dir,
    )

    print(f"Downloading {LLM_REPO}/{LLM_FILENAME} to {llm_dir}", flush=True)
    llm_path = Path(
        hf_hub_download(
            repo_id=LLM_REPO,
            filename=LLM_FILENAME,
            local_dir=llm_dir,
        )
    )
    actual_hash = file_sha256(llm_path)
    if actual_hash != LLM_SHA256:
        raise RuntimeError(
            f"Qwen model SHA-256 mismatch: expected {LLM_SHA256}, got {actual_hash}"
        )

    print("Models downloaded and verified.")
    print(f"ASR model: {asr_dir}")
    print(f"LLM model: {llm_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
