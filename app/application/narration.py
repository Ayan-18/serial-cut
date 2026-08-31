from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.infrastructure.config import Settings
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
    output_dir = settings.output_dir / "narration" / f"story-arc-{arc.id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = _safe_slug(arc.title)[:80] or f"story-arc-{arc.id}"
    script_path = output_dir / f"{slug}.txt"
    audio_path = output_dir / f"{slug}.wav"
    ps1_path = output_dir / "synthesize.ps1"
    script_path.write_text(narration.text, encoding="utf-8")
    ps1_path.write_text(_powershell_tts_script(), encoding="utf-8")
    result = runner(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1_path),
            str(script_path),
            str(audio_path),
        ],
        600,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Windows TTS не смог создать WAV")
    plan = dict(arc.plan_json or {})
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
$text = Get-Content -LiteralPath $TextPath -Raw -Encoding UTF8
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.Rate = 0
$speaker.Volume = 100
$speaker.SetOutputToWaveFile($OutputPath)
$speaker.Speak($text)
$speaker.Dispose()
"""
