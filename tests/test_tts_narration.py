from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from app.application.narration_voice import (
    auto_voice_for_character,
    guess_character_gender,
    resolve_narration_voice,
)
from app.media.tts import (
    DEFAULT_FEMALE_VOICE,
    DEFAULT_MALE_VOICE,
    SileroSynthesizer,
    StubTtsSynthesizer,
    WindowsSapiSynthesizer,
    build_synthesizer,
    voice_catalog,
)
from app.models.entities import Character, Season, StoryArc


def _character(session, name: str, description: str = "", voice: str | None = None) -> Character:
    season = session.scalar(__import__("sqlalchemy").select(Season)) if False else None
    if season is None:
        season = Season(title="S", root_path=f"C:/s-{name}")
        session.add(season)
        session.flush()
    character = Character(
        season_id=season.id,
        name=name,
        description=description,
        narration_voice=voice,
    )
    session.add(character)
    session.flush()
    return character


def test_voice_catalog_depends_on_adapter():
    assert {v.id for v in voice_catalog("silero")} == {"eugene", "aidar", "baya", "kseniya", "xenia"}
    assert [v.id for v in voice_catalog("windows-sapi")] == ["windows"]


@pytest.mark.parametrize(
    "name,description,expected",
    [
        ("Иван", "Молодой парень, брат главной героини", "male"),
        ("Мария", "Девушка, сестра Ивана", "female"),
        ("Сергей", "", "male"),
        ("Анна", "", "female"),
        ("Никита", "", "unknown"),
    ],
)
def test_guess_character_gender(name, description, expected):
    character = Character(season_id=1, name=name, description=description)
    assert guess_character_gender(character) == expected


def test_auto_voice_maps_gender_to_default_voice():
    male = Character(season_id=1, name="Сергей", description="")
    female = Character(season_id=1, name="Анна", description="")
    assert auto_voice_for_character(male, "eugene") == DEFAULT_MALE_VOICE
    assert auto_voice_for_character(female, "eugene") == DEFAULT_FEMALE_VOICE


def test_resolve_narration_voice_prefers_explicit_then_auto_then_narrator(session):
    character = _character(session, "Мария", "Девушка", voice="kseniya")
    arc = StoryArc(season_id=character.season_id, title="A", target_character_id=character.id)
    session.add(arc)
    session.flush()

    assert resolve_narration_voice(session, arc, "first_person", "eugene") == "kseniya"

    character.narration_voice = None
    session.flush()
    assert resolve_narration_voice(session, arc, "first_person", "eugene") == DEFAULT_FEMALE_VOICE

    assert resolve_narration_voice(session, arc, "narrator", "aidar") == "aidar"

    arc.target_character_id = None
    session.flush()
    assert resolve_narration_voice(session, arc, "first_person", "eugene") == "eugene"


def test_stub_synthesizer_writes_a_real_wav(tmp_path: Path):
    out = tmp_path / "line.wav"
    StubTtsSynthesizer(sample_rate=24000).synthesize("Тестовая строка озвучки", out, "eugene")
    with wave.open(str(out), "rb") as handle:
        assert handle.getframerate() == 24000
        assert handle.getnframes() > 0


def test_windows_sapi_synthesizer_invokes_powershell(tmp_path: Path):
    calls: list[list[str]] = []

    def fake_runner(args, timeout):
        calls.append(args)
        Path(args[-1]).write_bytes(b"RIFF....WAVE")
        from app.infrastructure.processes import ProcessResult

        return ProcessResult(args, 0, "", "")

    synth = WindowsSapiSynthesizer(tmp_path, runner=fake_runner)
    synth.synthesize("Привет", tmp_path / "out.wav", "windows")

    assert calls and calls[0][0] == "powershell"
    assert (tmp_path / "synthesize.ps1").exists()


def test_silero_synthesizer_reports_missing_model_or_torch(tmp_path: Path):
    synth = SileroSynthesizer(tmp_path / "missing_v4_ru.pt")
    with pytest.raises(RuntimeError, match="torch|Silero"):
        synth.synthesize("Текст", tmp_path / "out.wav", "eugene")


def test_build_synthesizer_selects_by_adapter(tmp_path: Path):
    class _S:
        tts_adapter = "stub"
        tts_sample_rate = 48000

    assert isinstance(build_synthesizer(_S(), tmp_path), StubTtsSynthesizer)
    _S.tts_adapter = "silero"
    assert isinstance(build_synthesizer(_S(), tmp_path), SileroSynthesizer)
    _S.tts_adapter = "windows-sapi"
    assert isinstance(build_synthesizer(_S(), tmp_path), WindowsSapiSynthesizer)


def test_tts_model_install_requires_confirmation_and_verifies(tmp_path, monkeypatch):
    from app.application import model_install

    monkeypatch.setattr(model_install, "_tts_dir", lambda: tmp_path / "tts")

    with pytest.raises(ValueError, match="Подтвердите"):
        model_install.install_model("tts", confirm=False)

    monkeypatch.setattr(model_install, "_verify_silero_model", lambda path: None)

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    entry = model_install.install_model(
        "tts", confirm=True, opener=lambda request, timeout: _Resp(b"x" * 4096)
    )
    assert entry.installed is True
    assert (tmp_path / "tts" / "v4_ru.pt").exists()


def test_verify_silero_model_rejects_tiny_file(tmp_path):
    from app.application import model_install

    bad = tmp_path / "v4_ru.pt"
    bad.write_bytes(b"too small")
    with pytest.raises(RuntimeError, match="размер"):
        model_install._verify_silero_model(bad)
    assert not bad.exists()
