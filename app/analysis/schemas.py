from __future__ import annotations

import json
import re
from typing import Annotated, Literal

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

ShortText = Annotated[str, Field(min_length=1, max_length=500)]


class OutlineTimeRange(BaseModel):
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    summary: ShortText

    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, value: float, info) -> float:
        start = info.data.get("start_time")
        if start is not None and value <= start:
            raise ValueError("end_time must be greater than start_time")
        return value


class EpisodeOutlinePayload(BaseModel):
    characters: list[ShortText] = Field(max_length=20)
    main_events: list[ShortText] = Field(max_length=12)
    conflicts: list[ShortText] = Field(max_length=12)
    time_ranges: list[OutlineTimeRange] = Field(max_length=12)
    summary: str = Field(min_length=1, max_length=1500)


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
    description: str = Field(min_length=1, max_length=500)
    moment_type: MomentType
    characters: list[ShortText] = Field(default_factory=list, max_length=20)
    score: int = Field(ge=0, le=100)
    scores: CandidateScores
    standalone_reason: str = Field(min_length=1, max_length=500)
    possible_problems: list[ShortText] = Field(default_factory=list, max_length=5)

    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, value: float, info) -> float:
        start = info.data.get("start_time")
        if start is not None and value <= start:
            raise ValueError("end_time must be greater than start_time")
        return value


class CandidateListPayload(BaseModel):
    candidates: list[CandidatePayload] = Field(max_length=8)


def parse_candidate_json(raw: str) -> CandidateListPayload:
    try:
        payload = json.loads(extract_json_object(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM вернул невалидный JSON: {exc}") from exc
    try:
        return CandidateListPayload.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"LLM JSON не прошёл схему кандидатов: {exc}") from exc


def extract_json_object(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^<think>.*?</think>\s*", "", text, flags=re.DOTALL)
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        return text[start : end + 1]
    return text

