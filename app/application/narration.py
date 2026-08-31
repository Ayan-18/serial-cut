from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.analysis.local_text import generate_local_text
from app.infrastructure.config import Settings
from app.infrastructure.atomic import replace_atomically, temp_sibling, write_text_atomically
from app.infrastructure.processes import ProcessResult, run_process
from app.models.entities import StoryArc


@dataclass(frozen=True)
class NarrationScript:
    story_arc_id: int
    text: str
    lines: list[dict]


@dataclass(frozen=True)
class NarrationAudio:
    story_arc_id: int
    audio_path: str
    script_path: str


def story_arc_narration(session: Session, story_arc_id: int) -> NarrationScript:
    arc = session.get(StoryArc, story_arc_id)
    if arc is None:
        raise ValueError("Арка не найдена")
    lines = list((arc.plan_json or {}).get("narration", []))
    if not lines:
        lines = _fallback_lines(arc)
    return NarrationScript(story_arc_id=arc.id, text=_join_lines(lines), lines=lines)


def synthesize_story_arc_narration(
    session: Session,
    story_arc_id: int,
    settings: Settings,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> NarrationAudio:
    arc = session.get(StoryArc, story_arc_id)
    if arc is None:
        raise ValueError("Арка не найдена")
    narration = story_arc_narration(session, story_arc_id)
    plan = dict(arc.plan_json or {})
    if not plan.get("narration_custom"):
        generated = generate_local_text(settings, _narration_prompt(arc), max_tokens=900)
        if generated:
            generated_lines = [
                {"order": index, "voice": "narrator", "text": line.strip(" -•\t")}
                for index, line in enumerate(generated.splitlines(), start=1)
                if line.strip(" -•\t")
            ]
            if generated_lines:
                narration = NarrationScript(arc.id, _join_lines(generated_lines), generated_lines)
                plan["narration"] = generated_lines
    output_dir = settings.output_dir / "narration" / f"story-arc-{arc.id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = _safe_slug(arc.title)[:80] or f"story-arc-{arc.id}"
    script_path = output_dir / f"{slug}.txt"
    audio_path = output_dir / f"{slug}.wav"
    ps1_path = output_dir / "synthesize.ps1"
    temp_audio_path = temp_sibling(audio_path).with_suffix(".wav")
    write_text_atomically(script_path, narration.text)
    write_text_atomically(ps1_path, _powershell_tts_script())
    result = runner(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1_path),
            str(script_path),
            str(temp_audio_path),
        ],
        600,
    )
    if result.returncode != 0:
        temp_audio_path.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "Windows TTS не смог создать WAV")
    if not temp_audio_path.exists():
        raise RuntimeError("Windows TTS завершился без WAV-файла")
    replace_atomically(temp_audio_path, audio_path)
    plan["narration_audio_path"] = str(audio_path)
    plan["narration_script_path"] = str(script_path)
    arc.plan_json = plan
    session.flush()
    return NarrationAudio(story_arc_id=arc.id, audio_path=str(audio_path), script_path=str(script_path))


def _fallback_lines(arc: StoryArc) -> list[dict]:
    chapters = list((arc.plan_json or {}).get("chapters", []))
    if not chapters:
        return [{"order": 1, "voice": "narrator", "text": f"Это монтажная история: {arc.title}."}]
    return [
        {
            "order": item.get("order", index),
            "voice": "narrator",
            "text": f"{item.get('title', 'Фрагмент')} показывает важный этап этой линии.",
        }
        for index, item in enumerate(chapters, start=1)
    ]


def _join_lines(lines: list[dict]) -> str:
    return "\n".join(str(item.get("text", "")).strip() for item in lines if str(item.get("text", "")).strip())


def _safe_slug(value: str) -> str:
    slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", value)
    slug = re.sub(r"\s+", " ", slug).strip(" .-_")
    return slug or "narration"


def _powershell_tts_script() -> str:
    return """param(
  [Parameter(Mandatory=$true)][string]$TextPath,
  [Parameter(Mandatory=$true)][string]$OutputPath
)
Add-Type -AssemblyName System.Speech
$culture = [System.Globalization.CultureInfo]::GetCultureInfo("ru-RU")
$text = Get-Content -LiteralPath $TextPath -Raw -Encoding UTF8
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = $speaker.GetInstalledVoices($culture) | Select-Object -First 1
if ($voice) { $speaker.SelectVoice($voice.VoiceInfo.Name) }
$speaker.Rate = 0
$speaker.Volume = 100
$speaker.SetOutputToWaveFile($OutputPath)
$speaker.Speak($text)
$speaker.Dispose()
"""


def _narration_prompt(arc: StoryArc) -> str:
    chapters = list((arc.plan_json or {}).get("chapters", []))
    chapter_text = "\n".join(
        f"{item.get('order')}. {item.get('title')} — роль {item.get('role')}, серия {item.get('episode')}"
        for item in chapters
    )
    max_words = max(25, min(220, round(arc.total_duration_seconds * 1.5)))
    perspective = (arc.plan_json or {}).get("target_character") or "нейтрального рассказчика"
    return (
        f"Напиши связный закадровый текст от лица {perspective}, максимум {max_words} слов. "
        "Каждая строка должна быть отдельной короткой связкой между монтажными частями. "
        "Не выдумывай новых фактов и не повторяй названия дословно.\n"
        f"Арка: {arc.title}\nЧасти:\n{chapter_text}"
    )
