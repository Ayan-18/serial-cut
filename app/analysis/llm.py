from __future__ import annotations

import logging
import re
from typing import Callable, Protocol

import httpx

from app.analysis.schemas import (
    AnalysisContext,
    CandidateListPayload,
    CandidatePayload,
    CandidateScores,
    EpisodeOutlinePayload,
    parse_candidate_json,
)
from app.models.entities import Scene
from app.infrastructure.processes import ProcessCancelledError


logger = logging.getLogger(__name__)


class EpisodeAnalyzer(Protocol):
    def outline(self, transcript: str, context: AnalysisContext | None = None) -> EpisodeOutlinePayload:
        ...

    def candidates(
        self,
        transcript: str,
        scenes: list[Scene],
        context: AnalysisContext | None = None,
        outline: EpisodeOutlinePayload | None = None,
    ) -> CandidateListPayload:
        ...


class StubEpisodeAnalyzer:
    def outline(self, transcript: str, context: AnalysisContext | None = None) -> EpisodeOutlinePayload:
        return EpisodeOutlinePayload(
            characters=[],
            main_events=["Проверочный фрагмент распознан локальным stub-анализатором"],
            conflicts=[],
            time_ranges=[{"start_time": 0.0, "end_time": 59.0, "summary": "Короткий тестовый блок"}],
            summary=(context.episode_summary if context and context.episode_summary else "Локальная тестовая карта эпизода для проверки конвейера."),
        )

    def candidates(
        self,
        transcript: str,
        scenes: list[Scene],
        context: AnalysisContext | None = None,
        outline: EpisodeOutlinePayload | None = None,
    ) -> CandidateListPayload:
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
                    story_role="завязка" if context and context.candidate_mode == "story" else None,
                    continuity_note=(
                        "Первая часть последовательного пересказа"
                        if context and context.candidate_mode == "story"
                        else None
                    ),
                )
            ]
        )


class LlamaCppHttpAnalyzer:
    def __init__(
        self,
        base_url: str,
        model_hint: str,
        timeout_seconds: int = 180,
        progress_callback: Callable[[float, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_hint = model_hint
        self.timeout_seconds = timeout_seconds
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check

    def outline(self, transcript: str, context: AnalysisContext | None = None) -> EpisodeOutlinePayload:
        self._raise_if_cancelled()
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
        ranges: list[dict] = []
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
        provided_summary = context.episode_summary.strip() if context else ""
        return EpisodeOutlinePayload(
            characters=[],
            main_events=[item["summary"] for item in ranges],
            conflicts=[],
            time_ranges=ranges[:12],
            summary=provided_summary or (
                f"Локальная карта эпизода: {entries[0][0]:.1f}-{entries[-1][1]:.1f} сек., "
                f"{len(entries)} распознанных реплик."
            ),
        )

    def candidates(
        self,
        transcript: str,
        scenes: list[Scene],
        context: AnalysisContext | None = None,
        outline: EpisodeOutlinePayload | None = None,
    ) -> CandidateListPayload:
        context = context or AnalysisContext()
        chunks = self._candidate_chunks(transcript, count=5 if context.candidate_mode == "story" else 3)
        all_candidates = []
        first_error: Exception | None = None
        logger.info(
            "Starting LLM candidate analysis: chunks=%s mode=%s scenes=%s",
            len(chunks),
            context.candidate_mode,
            len(scenes),
        )
        for chunk_index, chunk in enumerate(chunks, start=1):
            self._raise_if_cancelled()
            self._report(
                (chunk_index - 1) / max(1, len(chunks)),
                f"Qwen: часть {chunk_index} из {len(chunks)}",
            )
            entries = self._transcript_entries(chunk)
            if not entries:
                continue
            chunk_start, chunk_end = entries[0][0], entries[-1][1]
            scene_lines = "\n".join(
                f"{scene.start_time:.1f}-{scene.end_time:.1f}"
                for scene in scenes
                if scene.end_time >= chunk_start and scene.start_time <= chunk_end
            )
            selection_instruction = (
                "Выбери не более одного сюжетно необходимого фрагмента для последовательного пересказа. "
                "Он должен продолжать общую историю, не повторять соседние части и иметь роль: завязка, "
                "развитие, конфликт, поворот, кульминация или итог. Заполни story_role и continuity_note. "
                if context.candidate_mode == "story"
                else "Найди 1-2 сильных самостоятельных момента. "
            )
            prompt = (
                f"{selection_instruction}Работай только с частью серии "
                f"{chunk_start:.1f}-{chunk_end:.1f} сек. Используй числовые таймкоды расшифровки. "
                "Выбирай смысловой момент с понятной причиной и развязкой. Не начинай и не заканчивай "
                "посередине реплики; итоговые границы приложение "
                "сможет расширить до 35-59 секунд. Оцени каждый критерий и общий score честно по шкале "
                "0-100; пригодные моменты обычно получают 60-95. moment_type выбери из: юмор, конфликт, "
                "откровение, эмоциональный момент, напряжение, действие, запоминающаяся реплика, другое. "
                "Без markdown.\n\n"
                f"Контекст и требования:\n{self._context_prompt(context)}\n\n"
                f"Карта серии:\n{(outline.model_dump_json() if outline else 'не построена')}\n\n"
                f"Расшифровка выбранной части:\n{chunk}\n\nГраницы сцен:\n{scene_lines}"
            )
            try:
                parsed = self._candidates_for_prompt(prompt, chunk_index)
            except ValueError as exc:
                logger.warning("LLM candidate JSON validation failed: chunk=%s error=%s", chunk_index, exc)
                first_error = first_error or exc
                continue
            all_candidates.extend(parsed.candidates[:1] if context.candidate_mode == "story" else parsed.candidates[:2])
            self._report(
                chunk_index / max(1, len(chunks)),
                f"Qwen: обработана часть {chunk_index} из {len(chunks)}",
            )
        if not all_candidates and first_error is not None:
            raise first_error
        logger.info("LLM candidate analysis completed: candidates=%s", len(all_candidates))
        return CandidateListPayload(candidates=sorted(all_candidates, key=lambda item: item.start_time)[:8])

    def _candidates_for_prompt(
        self,
        prompt: str,
        chunk_index: int,
        max_attempts: int = 2,
    ) -> CandidateListPayload:
        """Ask the local model for candidates, retrying once on invalid JSON.

        Small local models occasionally emit truncated or markdown-wrapped JSON.
        A single stricter retry recovers most of those without a visible failure.
        """
        schema = CandidateListPayload.model_json_schema()
        last_error: ValueError | None = None
        for attempt in range(1, max_attempts + 1):
            self._raise_if_cancelled()
            attempt_prompt = prompt
            if attempt > 1:
                attempt_prompt = (
                    f"{prompt}\n\nПредыдущий ответ не был валидным JSON "
                    f"({last_error}). Верни строго один JSON-объект по схеме, без markdown и текста вокруг."
                )
            try:
                return parse_candidate_json(
                    self._complete_json(attempt_prompt, schema, max_tokens=1600)
                )
            except ValueError as exc:
                last_error = exc
                logger.warning(
                    "LLM candidate JSON invalid: chunk=%s attempt=%s/%s error=%s",
                    chunk_index,
                    attempt,
                    max_attempts,
                    exc,
                )
        assert last_error is not None
        raise last_error

    @staticmethod
    def _context_prompt(context: AnalysisContext) -> str:
        required = "; ".join(context.required_events) or "нет обязательных событий"
        excluded = "; ".join(context.excluded_events) or "нет исключений"
        return (
            f"Режим: {'связный пересказ серии' if context.candidate_mode == 'story' else 'лучшие самостоятельные моменты'}.\n"
            f"Контекст сезона: {context.season_summary or 'не задан'}.\n"
            f"Суть серии: {context.episode_summary or 'определи по расшифровке'}.\n"
            f"Обязательно показать: {required}.\n"
            f"Не включать: {excluded}.\n"
            f"Спойлеры: {'разрешены' if context.spoilers_allowed else 'не раскрывай концовку'}"
        )

    def _complete_json(self, prompt: str, schema: dict, max_tokens: int) -> str:
        self._raise_if_cancelled()
        logger.info("Sending request to local llama.cpp: base_url=%s max_tokens=%s", self.base_url, max_tokens)
        try:
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
        except httpx.ConnectError as exc:
            logger.warning("Local llama.cpp connection failed: base_url=%s", self.base_url)
            raise RuntimeError(
                "Локальная Qwen недоступна. Перезапустите приложение через scripts\\run.ps1 "
                "или scripts\\run_local.ps1."
            ) from exc
        except httpx.TimeoutException as exc:
            logger.warning("Local llama.cpp timed out: base_url=%s timeout=%s", self.base_url, self.timeout_seconds)
            raise RuntimeError("Локальная Qwen не ответила вовремя. Попробуйте запустить поиск ещё раз.") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Local llama.cpp rejected request: base_url=%s status=%s",
                self.base_url,
                exc.response.status_code,
            )
            raise RuntimeError(f"Локальная Qwen отклонила запрос: HTTP {exc.response.status_code}") from exc
        payload = response.json()
        self._raise_if_cancelled()
        choices = payload.get("choices") or []
        if choices:
            return str((choices[0].get("message") or {}).get("content") or "")
        return str(payload.get("content") or payload.get("response") or "")

    def _raise_if_cancelled(self) -> None:
        if self.cancel_check is not None and self.cancel_check():
            raise ProcessCancelledError("Анализ Qwen остановлен пользователем")

    def _report(self, value: float, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(max(0.0, min(1.0, value)), message)

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

