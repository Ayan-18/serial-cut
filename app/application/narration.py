from __future__ import annotations

import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.analysis.local_text import generate_local_text
from app.application.narration_voice import resolve_narration_voice
from app.infrastructure.config import Settings
from app.infrastructure.atomic import replace_atomically, temp_sibling, write_text_atomically
from app.infrastructure.processes import ProcessResult, run_process
from app.media.ru_numbers import normalize_numbers
from app.media.tts import DEFAULT_NARRATOR_VOICE, TtsSynthesizer, build_synthesizer
from app.models.entities import StoryArc


@dataclass(frozen=True)
class NarrationScript:
    story_arc_id: int
    text: str
    lines: list[dict]
    mode: str = "first_person"
    # "llm" - written by local Qwen; "template" - generic fallback (Qwen was
    # unavailable); "manual" - user-edited draft.
    source: str = "template"
    tts_notice: str = "Локальная TTS-озвучка не имитирует голос актёра или персонажа."


@dataclass(frozen=True)
class NarrationAudio:
    story_arc_id: int
    audio_path: str
    script_path: str


def story_arc_narration(session: Session, story_arc_id: int, narration_mode: str = "first_person") -> NarrationScript:
    arc = session.get(StoryArc, story_arc_id)
    if arc is None:
        raise ValueError("Арка не найдена")
    mode = _effective_narration_mode(arc, narration_mode)
    plan = arc.plan_json or {}
    lines = list(plan.get("narration", []))
    if mode == "narrator":
        lines = [_as_narrator_line(item) for item in lines]
    if lines:
        source = "manual" if plan.get("narration_custom") else str(plan.get("narration_source") or "llm")
    else:
        lines = _fallback_lines(arc, mode)
        source = "template"
    return NarrationScript(story_arc_id=arc.id, text=_join_lines(lines), lines=lines, mode=mode, source=source)


def synthesize_story_arc_narration(
    session: Session,
    story_arc_id: int,
    settings: Settings,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
    target_duration_seconds: float | None = None,
    narration_mode: str = "first_person",
    synthesizer: TtsSynthesizer | None = None,
) -> NarrationAudio:
    arc = session.get(StoryArc, story_arc_id)
    if arc is None:
        raise ValueError("Арка не найдена")
    mode = _effective_narration_mode(arc, narration_mode)
    if mode == "none":
        raise ValueError("Озвучка выключена для этого StoryArc")
    narration = story_arc_narration(session, story_arc_id, mode)
    plan = dict(arc.plan_json or {})
    source = "manual" if plan.get("narration_custom") else "template"
    if not plan.get("narration_custom"):
        generated = generate_local_text(settings, _narration_prompt(arc, mode), max_tokens=900)
        if generated:
            generated_lines = [
                {"order": index, "voice": _line_voice(arc, mode), "text": line.strip(" -•\t")}
                for index, line in enumerate(generated.splitlines(), start=1)
                if line.strip(" -•\t")
            ]
            if generated_lines:
                source = "llm"
                narration = NarrationScript(arc.id, _join_lines(generated_lines), generated_lines, mode=mode)
    target_duration = max(1.0, float(target_duration_seconds or arc.total_duration_seconds))
    timed_lines = _timed_lines(
        narration.lines,
        list(plan.get("chapters") or []),
        target_duration,
    )
    if not timed_lines:
        raise ValueError("Для озвучки нет непустых строк")
    narration = NarrationScript(arc.id, _join_lines(timed_lines), timed_lines)
    plan["narration"] = timed_lines
    output_dir = settings.output_dir / "narration" / f"story-arc-{arc.id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = _safe_slug(arc.title)[:80] or f"story-arc-{arc.id}"
    script_path = output_dir / f"{slug}.txt"
    audio_path = output_dir / f"{slug}.wav"
    temp_audio_path = temp_sibling(audio_path).with_suffix(".wav")
    parts_dir = output_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomically(script_path, narration.text)
    synthesizer = synthesizer or build_synthesizer(settings, output_dir, runner=runner)
    voice_id = resolve_narration_voice(
        session, arc, mode, getattr(settings, "tts_narrator_voice", DEFAULT_NARRATOR_VOICE)
    )
    part_paths: list[Path] = []
    part_durations: list[float] = []
    for index, line in enumerate(timed_lines, start=1):
        part_audio = parts_dir / f"line-{index:02}.wav"
        temp_part = temp_sibling(part_audio).with_suffix(".wav")
        line_voice = str(line.get("voice_id") or voice_id)
        spoken = normalize_numbers(str(line["text"]))
        try:
            synthesizer.synthesize(spoken, temp_part, line_voice)
        except RuntimeError:
            temp_part.unlink(missing_ok=True)
            raise
        if not temp_part.exists():
            raise RuntimeError(f"Синтез озвучки не создал WAV для строки {index}")
        replace_atomically(temp_part, part_audio)
        duration = _wav_duration_seconds(part_audio)
        line["audio_duration_seconds"] = round(duration, 3)
        line["voice_id"] = line_voice
        part_paths.append(part_audio)
        part_durations.append(duration)
    timeline_result = runner(
        build_narration_timeline_args(
            settings.ffmpeg_path,
            part_paths,
            timed_lines,
            part_durations,
            target_duration,
            temp_audio_path,
        ),
        600,
    )
    if timeline_result.returncode != 0:
        temp_audio_path.unlink(missing_ok=True)
        raise RuntimeError(timeline_result.stderr.strip() or "FFmpeg не смог собрать таймлайн озвучки")
    if not temp_audio_path.exists():
        raise RuntimeError("FFmpeg завершился без итогового WAV-файла")
    replace_atomically(temp_audio_path, audio_path)
    plan["narration_audio_path"] = str(audio_path)
    plan["narration_script_path"] = str(script_path)
    plan["narration_timeline_version"] = 2
    plan["narration_duration_seconds"] = round(target_duration, 3)
    plan["narration_mode"] = mode
    plan["narration_voice"] = voice_id
    plan["narration_source"] = source
    plan["narration"] = timed_lines
    arc.plan_json = plan
    session.flush()
    return NarrationAudio(story_arc_id=arc.id, audio_path=str(audio_path), script_path=str(script_path))


def _fallback_lines(arc: StoryArc, narration_mode: str = "first_person") -> list[dict]:
    chapters = list((arc.plan_json or {}).get("chapters", []))
    voice = _line_voice(arc, narration_mode)
    if not chapters:
        return [{"order": 1, "voice": voice, "text": f"Это монтажная история: {arc.title}."}]
    elapsed = 0.0
    result = []
    for index, item in enumerate(chapters, start=1):
        result.append(
        {
            "order": item.get("order", index),
            "voice": voice,
            "text": _fallback_text(item.get("title", "Фрагмент"), narration_mode),
            "start_time": round(elapsed + 0.35, 3),
        }
        )
        elapsed += float(item.get("duration") or 0.0)
    return result


def build_narration_timeline_args(
    ffmpeg_path: str,
    part_paths: list[Path],
    lines: list[dict],
    durations: list[float],
    target_duration: float,
    output_path: Path,
) -> list[str]:
    if not part_paths or len(part_paths) != len(lines) or len(lines) != len(durations):
        raise ValueError("Для таймлайна нужны все WAV-строки и их длительности")
    args = [ffmpeg_path, "-hide_banner", "-y"]
    for path in part_paths:
        args.extend(["-i", str(path)])
    filters: list[str] = []
    labels: list[str] = []
    for index, (line, duration) in enumerate(zip(lines, durations, strict=True)):
        start = max(0.0, float(line.get("start_time") or 0.0))
        next_start = (
            max(start + 0.1, float(lines[index + 1].get("start_time") or target_duration))
            if index + 1 < len(lines)
            else target_duration
        )
        available = max(0.1, next_start - start - 0.2)
        tempo = max(1.0, duration / available)
        if tempo > 1.35:
            raise ValueError(
                f"Строка озвучки {index + 1} не помещается в монтажный интервал; сократите текст"
            )
        label = f"voice{index}"
        delay_ms = round(start * 1000)
        filters.append(
            f"[{index}:a]aresample=48000,atempo={tempo:.4f},"
            f"adelay={delay_ms}:all=1[{label}]"
        )
        labels.append(f"[{label}]")
    filters.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"apad,atrim=duration={target_duration:.3f}[narration]"
    )
    args.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[narration]",
            "-t",
            f"{target_duration:.3f}",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )
    return args


def _timed_lines(lines: list[dict], chapters: list[dict], total_duration: float) -> list[dict]:
    chapter_starts: dict[int, float] = {}
    elapsed = 0.0
    for index, chapter in enumerate(chapters, start=1):
        order = int(chapter.get("order") or index)
        chapter_starts[order] = elapsed + 0.35
        elapsed += float(chapter.get("duration") or 0.0)
    result: list[dict] = []
    clean_lines = [dict(item) for item in lines if str(item.get("text") or "").strip()]
    align_to_chapters = bool(chapters) and len(clean_lines) <= len(chapters)
    for index, item in enumerate(clean_lines, start=1):
        order = int(item.get("order") or index)
        fallback = (index - 1) * total_duration / max(1, len(clean_lines)) + 0.35
        if item.get("start_time") is not None:
            start = float(item["start_time"])
        elif align_to_chapters:
            start = chapter_starts.get(order, fallback)
        else:
            # A local generator may return more connective lines than there are
            # chapters. Even spacing keeps them ordered and prevents collisions.
            start = fallback
        item["order"] = order
        item["text"] = str(item["text"]).strip()
        item["start_time"] = round(min(max(0.0, start), max(0.0, total_duration - 0.25)), 3)
        result.append(item)
    return sorted(result, key=lambda item: (float(item["start_time"]), int(item["order"])))


def _wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / max(1, handle.getframerate())
    except (OSError, wave.Error) as exc:
        raise RuntimeError(f"Не удалось проверить длительность WAV: {path.name}") from exc


def _join_lines(lines: list[dict]) -> str:
    return "\n".join(str(item.get("text", "")).strip() for item in lines if str(item.get("text", "")).strip())


def _safe_slug(value: str) -> str:
    slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", value)
    slug = re.sub(r"\s+", " ", slug).strip(" .-_")
    return slug or "narration"




def _narration_prompt(arc: StoryArc, narration_mode: str = "first_person") -> str:
    chapters = list((arc.plan_json or {}).get("chapters", []))
    chapter_text = "\n".join(
        f"{item.get('order')}. {item.get('title')} — роль {item.get('role')}, серия {item.get('episode')}"
        for item in chapters
    )
    max_words = max(25, min(220, round(arc.total_duration_seconds * 1.5)))
    target_character = (arc.plan_json or {}).get("target_character")
    perspective = target_character if narration_mode == "first_person" and target_character else "нейтрального рассказчика"
    wording = "от первого лица" if narration_mode == "first_person" and target_character else "от нейтрального рассказчика"
    return (
        f"Напиши связный закадровый текст {wording} ({perspective}), максимум {max_words} слов. "
        "Каждая строка должна быть отдельной короткой связкой между монтажными частями. "
        "Не выдумывай новых фактов и не повторяй названия дословно.\n"
        f"Арка: {arc.title}\nЧасти:\n{chapter_text}"
    )


def _normalize_narration_mode(value: str) -> str:
    return value if value in {"narrator", "first_person", "none"} else "first_person"


def _effective_narration_mode(arc: StoryArc, value: str) -> str:
    mode = _normalize_narration_mode(value)
    if mode == "first_person" and not (arc.plan_json or {}).get("target_character"):
        return "narrator"
    return mode


def _line_voice(arc: StoryArc, narration_mode: str) -> str:
    target_character = (arc.plan_json or {}).get("target_character")
    if narration_mode == "first_person" and target_character:
        return str(target_character)
    return "narrator"


def _as_narrator_line(item: dict) -> dict:
    line = dict(item)
    line["voice"] = "narrator"
    return line


def _fallback_text(title: object, narration_mode: str) -> str:
    if narration_mode == "first_person":
        return f"Этот момент стал важным этапом моей истории: {title}."
    return f"{title} показывает важный этап этой линии."
