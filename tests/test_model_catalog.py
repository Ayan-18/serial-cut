from __future__ import annotations

import io

import pytest

from app.application import model_install


def test_model_catalog_lists_asr_llm_face_and_tts_entries():
    entries = {entry.key: entry for entry in model_install.model_catalog()}

    assert set(entries) == {"asr", "llm", "face", "tts"}
    assert entries["llm"].approx_size_mb > entries["face"].approx_size_mb
    assert entries["asr"].installable_in_app is False
    assert entries["face"].installable_in_app is True
    assert entries["tts"].installable_in_app is True
    assert "install_identity_models" in entries["face"].install_command
    assert "install_tts_model" in entries["tts"].install_command


def test_install_requires_confirmation():
    with pytest.raises(ValueError, match="Подтвердите"):
        model_install.install_model("face", confirm=False)


def test_install_rejects_large_models_from_the_ui():
    with pytest.raises(ValueError, match="ставится командой"):
        model_install.install_model("asr", confirm=True)


def test_install_face_models_downloads_and_verifies(tmp_path, monkeypatch):
    face_dir = tmp_path / "face"
    monkeypatch.setattr(model_install, "_face_dir", lambda: face_dir)
    monkeypatch.setattr(
        model_install,
        "FACE_MODELS",
        (("weights.onnx", "https://example/weights.onnx", _sha256(b"WEIGHTS")),),
    )

    class _FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def fake_opener(request, timeout):
        return _FakeResponse(b"WEIGHTS")

    entry = model_install.install_model("face", confirm=True, opener=fake_opener)

    assert entry.installed is True
    assert (face_dir / "weights.onnx").read_bytes() == b"WEIGHTS"


def test_install_face_models_rejects_hash_mismatch(tmp_path, monkeypatch):
    face_dir = tmp_path / "face"
    monkeypatch.setattr(model_install, "_face_dir", lambda: face_dir)
    monkeypatch.setattr(
        model_install,
        "FACE_MODELS",
        (("weights.onnx", "https://example/weights.onnx", "0" * 64),),
    )

    class _FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    with pytest.raises(RuntimeError, match="SHA-256"):
        model_install.install_model(
            "face", confirm=True, opener=lambda request, timeout: _FakeResponse(b"WRONG")
        )
    assert not (face_dir / "weights.onnx").exists()


def _sha256(data: bytes) -> str:
    from hashlib import sha256

    return sha256(data).hexdigest()
