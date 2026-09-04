from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from app.infrastructure.atomic import write_text_atomically
from app.infrastructure.processes import ProcessResult, run_process

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TtsVoice:
    id: str
    label: str
    gender: str  # "male" | "female" | "neutral"


# Silero v4_ru speakers. All local, no cloning of any real person.
SILERO_VOICES: tuple[TtsVoice, ...] = (
    TtsVoice("eugene", "Евгений (муж.)", "male"),
    TtsVoice("aidar", "Айдар (муж.)", "male"),
    TtsVoice("baya", "Байя (жен.)", "female"),
    TtsVoice("kseniya", "Ксения (жен.)", "female"),
    TtsVoice("xenia", "Ксения мягкая (жен.)", "female"),
)
SILERO_VOICE_IDS = frozenset(voice.id for voice in SILERO_VOICES)
DEFAULT_MALE_VOICE = "eugene"
DEFAULT_FEMALE_VOICE = "baya"
DEFAULT_NARRATOR_VOICE = "eugene"


def voice_catalog(adapter: str) -> list[TtsVoice]:
    if adapter == "silero":
        return list(SILERO_VOICES)
    return [TtsVoice("windows", "Голос Windows по умолчанию", "neutral")]


class TtsSynthesizer(Protocol):
    def synthesize(self, text: str, output_path: Path, voice: str) -> None:
        """Write a mono WAV rendering of ``text`` to ``output_path``."""


# --- Windows SAPI (System.Speech) ------------------------------------------------

_POWERSHELL_TTS_SCRIPT = """param(
  [Parameter(Mandatory=$true)][string]$TextPath,
  [Parameter(Mandatory=$true)][string]$OutputPath
)
Add-Type -AssemblyName System.Speech
$culture = [System.Globalization.CultureInfo]::GetCultureInfo("ru-RU")
$text = Get-Content -LiteralPath $TextPath -Raw -Encoding UTF8
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = $speaker.GetInstalledVoices($culture) | Where-Object { $_.Enabled } | Select-Object -First 1
if (-not $voice) {
  [Console]::Error.WriteLine("В Windows нет русского голоса (ru-RU). Параметры -> Время и язык -> Речь.")
  exit 3
}
$speaker.SelectVoice($voice.VoiceInfo.Name)
$speaker.Rate = 0
$speaker.Volume = 100
$speaker.SetOutputToWaveFile($OutputPath)
$speaker.Speak($text)
$speaker.Dispose()
"""


def powershell_tts_script() -> str:
    return _POWERSHELL_TTS_SCRIPT


class WindowsSapiSynthesizer:
    def __init__(
        self,
        script_dir: Path,
        runner: Callable[[list[str], int], ProcessResult] = run_process,
    ) -> None:
        self.script_path = script_dir / "synthesize.ps1"
        self.runner = runner
        write_text_atomically(self.script_path, _POWERSHELL_TTS_SCRIPT)

    def synthesize(self, text: str, output_path: Path, voice: str) -> None:
        text_path = output_path.with_suffix(".txt")
        write_text_atomically(text_path, text)
        result = self.runner(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.script_path),
                str(text_path),
                str(output_path),
            ],
            600,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Windows TTS не смог озвучить строку")
        if not output_path.exists():
            raise RuntimeError("Windows TTS завершился без WAV-файла")


# --- Silero (local neural TTS) --------------------------------------------------


class SileroSynthesizer:
    """Local Silero v4_ru neural TTS. CPU is enough; the GPU stays free."""

    _model_cache: dict[str, object] = {}

    def __init__(self, model_path: Path, sample_rate: int = 48000) -> None:
        self.model_path = Path(model_path)
        self.sample_rate = sample_rate if sample_rate in (8000, 24000, 48000) else 48000

    def _model(self):
        key = str(self.model_path.resolve())
        cached = self._model_cache.get(key)
        if cached is not None:
            return cached
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Silero TTS требует пакет torch. Установите: "
                ".\\.venv\\Scripts\\python.exe -m pip install -e \".[tts]\""
            ) from exc
        if not self.model_path.exists():
            raise RuntimeError(
                f"Модель Silero не найдена: {self.model_path}. "
                "Установите её в разделе «Локальные модели» или scripts\\install_tts_model.ps1"
            )
        torch.set_num_threads(max(1, min(8, (torch.get_num_threads() or 4))))
        model = torch.package.PackageImporter(str(self.model_path)).load_pickle("tts_models", "model")
        model.to(torch.device("cpu"))
        self._model_cache[key] = model
        return model

    def synthesize(self, text: str, output_path: Path, voice: str) -> None:
        speaker = voice if voice in SILERO_VOICE_IDS else DEFAULT_NARRATOR_VOICE
        model = self._model()
        clean = text.strip()
        if not clean:
            raise RuntimeError("Silero TTS: пустой текст строки")
        audio = model.apply_tts(
            text=clean,
            speaker=speaker,
            sample_rate=self.sample_rate,
            put_accent=True,
            put_yo=True,
        )
        import torch

        samples = (torch.clamp(audio, -1.0, 1.0) * 32767).to(torch.int16).cpu().numpy()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self.sample_rate)
            handle.writeframes(samples.tobytes())


# --- Stub (deterministic, offline) --------------------------------------------


class StubTtsSynthesizer:
    def __init__(self, sample_rate: int = 48000, seconds_per_char: float = 0.05) -> None:
        self.sample_rate = sample_rate
        self.seconds_per_char = seconds_per_char

    def synthesize(self, text: str, output_path: Path, voice: str) -> None:
        seconds = max(0.4, len(text.strip()) * self.seconds_per_char)
        frames = int(seconds * self.sample_rate)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self.sample_rate)
            handle.writeframes(b"\x00\x00" * frames)


def build_synthesizer(
    settings,
    script_dir: Path,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> TtsSynthesizer:
    adapter = getattr(settings, "tts_adapter", "windows-sapi")
    if adapter == "silero":
        return SileroSynthesizer(
            Path(getattr(settings, "tts_model_path", "./data/models/tts/v4_ru.pt")),
            int(getattr(settings, "tts_sample_rate", 48000)),
        )
    if adapter == "stub":
        return StubTtsSynthesizer(int(getattr(settings, "tts_sample_rate", 48000)))
    return WindowsSapiSynthesizer(script_dir, runner=runner)
