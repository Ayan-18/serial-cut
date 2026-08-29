from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator


MomentType = Literal[
    "юмор",
    "конфликт",
    "откровение",
    "эмоциональный момент",
    "напряжение",
    "действие",
    "запоминающаяся реплика",
    "другое",
]


class EpisodeOutlinePayload(BaseModel):
    characters: list[str] = Field(default_factory=list)
    main_events: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    time_ranges: list[dict] = Field(default_factory=list)
    summary: str


class CandidateScores(BaseModel):
    hook: int = Field(ge=0, le=100)
    standalone_context: int = Field(ge=0, le=100)
    payoff: int = Field(ge=0, le=100)
    emotion: int = Field(ge=0, le=100)
    boundary_quality: int = Field(ge=0, le=100)
    visual_potential: int = Field(ge=0, le=100)
    audio_quality: int = Field(ge=0, le=100)


class CandidatePayload(BaseModel):
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    moment_type: MomentType
    characters: list[str] = Field(default_factory=list)
    score: int = Field(ge=0, le=100)
    scores: CandidateScores
    standalone_reason: str = Field(min_length=1)
    possible_problems: list[str] = Field(default_factory=list)

    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, value: float, info) -> float:
        start = info.data.get("start_time")
        if start is not None and value <= start:
            raise ValueError("end_time must be greater than start_time")
        return value


class CandidateListPayload(BaseModel):
    candidates: list[CandidatePayload]


def parse_candidate_json(raw: str) -> CandidateListPayload:
    try:
        payload = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM вернул невалидный JSON: {exc}") from exc
    try:
        return CandidateListPayload.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"LLM JSON не прошёл схему кандидатов: {exc}") from exc


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text

