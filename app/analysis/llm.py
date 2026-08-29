from __future__ import annotations

from typing import Protocol

import httpx

from app.analysis.schemas import (
    CandidateListPayload,
    CandidatePayload,
    CandidateScores,
    EpisodeOutlinePayload,
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
        prompt = (
            "Ты анализируешь русскую расшифровку серии. Верни строго JSON с ключами "
            "characters, main_events, conflicts, time_ranges, summary. Без markdown.\n\n"
            f"Расшифровка:\n{transcript[:16000]}"
        )
        return EpisodeOutlinePayload.model_validate_json(self._complete_json(prompt))

    def candidates(self, transcript: str, scenes: list[Scene]) -> CandidateListPayload:
        scene_lines = "\n".join(f"{s.start_time:.1f}-{s.end_time:.1f}" for s in scenes[:400])
        prompt = (
            "Найди законченные фрагменты для Shorts/Reels. Верни строго JSON вида "
            '{"candidates":[{"start_time":0,"end_time":45,"title":"...","description":"...",'
            '"moment_type":"юмор|конфликт|откровение|эмоциональный момент|напряжение|действие|'
            'запоминающаяся реплика|другое","characters":[],"score":0,'
            '"scores":{"hook":0,"standalone_context":0,"payoff":0,"emotion":0,'
            '"boundary_quality":0,"visual_potential":0,"audio_quality":0},'
            '"standalone_reason":"...","possible_problems":[]}]}. Без markdown.\n\n'
            f"Сцены:\n{scene_lines}\n\nРасшифровка:\n{transcript[:18000]}"
        )
        return parse_candidate_json(self._complete_json(prompt))

    def _complete_json(self, prompt: str) -> str:
        response = httpx.post(
            f"{self.base_url}/completion",
            json={
                "prompt": prompt,
                "temperature": 0.1,
                "n_predict": 2048,
                "cache_prompt": True,
                "stop": ["</s>"],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload.get("content") or payload.get("response") or "")

