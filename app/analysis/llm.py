from __future__ import annotations

import re
from typing import Protocol

import httpx

from app.analysis.schemas import (
    CandidateListPayload,
    CandidatePayload,
    CandidateScores,
    EpisodeOutlinePayload,
    extract_json_object,
    parse_candidate_json,
)
from app.models.entities import Scene


class EpisodeAnalyzer(Protocol):
    def outline(self, transcript: str) -> EpisodeOutlinePayload:
        ...

    def candidates(self, transcript: str, scenes: list[Scene]) -> CandidateListPayload:
        ...


class StubEpisodeAnalyzer:
    def outline(self, transcript: str) -> EpisodeOutlinePayload:
        return EpisodeOutlinePayload(
            characters=[],
            main_events=["Проверочный фрагмент распознан локальным stub-анализатором"],
            conflicts=[],
            time_ranges=[{"start_time": 0.0, "end_time": 59.0, "summary": "Короткий тестовый блок"}],
            summary="Локальная тестовая карта эпизода для проверки конвейера.",
        )

    def candidates(self, transcript: str, scenes: list[Scene]) -> CandidateListPayload:
        start = scenes[0].start_time if scenes else 0.0
        end = scenes[0].end_time if scenes else 45.0
        if end - start < 35:
            end = start + 35
        return CandidateListPayload(
            candidates=[
                CandidatePayload(
                    start_time=start,
                    end_time=min(end, start + 59),
                    title="Проверочный момент",
                    description="Синтетический кандидат для smoke-прохода локального конвейера.",
                    moment_type="другое",
                    characters=[],
                    score=86,
                    scores=CandidateScores(
                        hook=80,
                        standalone_context=88,
                        payoff=82,
                        emotion=70,
                        boundary_quality=84,
                        visual_potential=72,
                        audio_quality=90,
                    ),
                    standalone_reason="Фрагмент содержит цельную реплику и не требует предыдущей сцены.",
                    possible_problems=[],
                )
            ]
        )


class LlamaCppHttpAnalyzer:
    def __init__(self, base_url: str, model_hint: str, timeout_seconds: int = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_hint = model_hint
        self.timeout_seconds = timeout_seconds

    def outline(self, transcript: str) -> EpisodeOutlinePayload:
        entries = self._transcript_entries(transcript)
        if not entries:
            return EpisodeOutlinePayload(
                characters=[],
                main_events=[transcript[:500] or "Расшифровка без текста"],
                conflicts=[],
                time_ranges=[],
                summary="Локальная карта построена без распознанных таймкодов.",
            )
        bucket_count = min(8, max(1, round(entries[-1][1] / 120)))
        bucket_size = max(1, (len(entries) + bucket_count - 1) // bucket_count)
        ranges = []
        for index in range(0, len(entries), bucket_size):
            bucket = entries[index : index + bucket_size]
            summary = " ".join(entry[2] for entry in bucket).strip()[:500]
            ranges.append(
                {
                    "start_time": bucket[0][0],
                    "end_time": bucket[-1][1],
                    "summary": summary or f"Часть эпизода {len(ranges) + 1}",
                }
            )
        return EpisodeOutlinePayload(
            characters=[],
            main_events=[item["summary"] for item in ranges],
            conflicts=[],
            time_ranges=ranges[:12],
            summary=(
                f"Локальная карта эпизода: {entries[0][0]:.1f}-{entries[-1][1]:.1f} сек., "
                f"{len(entries)} распознанных реплик."
            ),
        )

    def candidates(self, transcript: str, scenes: list[Scene]) -> CandidateListPayload:
        chunks = self._candidate_chunks(transcript, count=3)
        all_candidates = []
        first_error: Exception | None = None
        for chunk in chunks:
            entries = self._transcript_entries(chunk)
            if not entries:
                continue
            chunk_start, chunk_end = entries[0][0], entries[-1][1]
            scene_lines = "\n".join(
                f"{scene.start_time:.1f}-{scene.end_time:.1f}"
                for scene in scenes
                if scene.end_time >= chunk_start and scene.start_time <= chunk_end
            )
            prompt = (
                f"Найди 1-2 законченных фрагмента для Shorts/Reels только в части серии "
                f"{chunk_start:.1f}-{chunk_end:.1f} сек. Используй числовые таймкоды расшифровки. "
                "Выбирай смысловой момент с понятным началом и развязкой; итоговые границы приложение "
                "сможет расширить до 35-59 секунд. Оцени каждый критерий и общий score честно по шкале "
                "0-100; пригодные моменты обычно получают 60-95. moment_type выбери из: юмор, конфликт, "
                "откровение, эмоциональный момент, напряжение, действие, запоминающаяся реплика, другое. "
                "Без markdown.\n\n"
                f"Расшифровка:\n{chunk}\n\nГраницы сцен:\n{scene_lines}"
            )
            try:
                parsed = parse_candidate_json(
                    self._complete_json(prompt, CandidateListPayload.model_json_schema(), max_tokens=1600)
                )
            except (httpx.HTTPError, ValueError) as exc:
                first_error = first_error or exc
                continue
            all_candidates.extend(parsed.candidates[:2])
        if not all_candidates and first_error is not None:
            raise first_error
        return CandidateListPayload(candidates=all_candidates[:8])

    def _complete_json(self, prompt: str, schema: dict, max_tokens: int) -> str:
        response = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json={
                "messages": [
                    {
                        "role": "system",
                        "content": "Отвечай только валидным JSON без markdown и пояснений.",
                    },
                    {"role": "user", "content": f"/no_think\n{prompt}"},
                ],
                "temperature": 0.2,
                "top_p": 0.8,
                "max_tokens": max_tokens,
                "response_format": {
                    "type": "json_object",
                    "schema": self._grammar_schema(schema),
                },
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        if choices:
            return str((choices[0].get("message") or {}).get("content") or "")
        return str(payload.get("content") or payload.get("response") or "")

    @classmethod
    def _grammar_schema(cls, value):
        """Remove size constraints that expand into oversized llama.cpp grammars."""
        if isinstance(value, dict):
            return {
                key: cls._grammar_schema(item)
                for key, item in value.items()
                if key not in {"maxLength", "minLength", "maxItems", "minItems"}
            }
        if isinstance(value, list):
            return [cls._grammar_schema(item) for item in value]
        return value

    @staticmethod
    def _transcript_entries(transcript: str) -> list[tuple[float, float, str]]:
        pattern = re.compile(r"^\[([0-9.]+)-([0-9.]+)\]\s*(.*)$", re.MULTILINE)
        return [
            (float(match.group(1)), float(match.group(2)), match.group(3).strip())
            for match in pattern.finditer(transcript)
            if float(match.group(2)) > float(match.group(1))
        ]

    @classmethod
    def _candidate_chunks(cls, transcript: str, count: int) -> list[str]:
        entries = cls._transcript_entries(transcript)
        if not entries:
            return [transcript]
        count = min(count, len(entries))
        chunk_size = max(1, (len(entries) + count - 1) // count)
        chunks = []
        for index in range(0, len(entries), chunk_size):
            lines = [f"[{start:.1f}-{end:.1f}] {text}" for start, end, text in entries[index : index + chunk_size]]
            chunks.append("\n".join(lines))
        return chunks[:count]

