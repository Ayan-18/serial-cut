from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    color: str = Field(default="#b9ddff", pattern="^#[0-9a-fA-F]{6}$")
    photo_data_url: str | None = Field(default=None, max_length=12_000_000)


class CharacterPhotoAdd(BaseModel):
    photo_data_url: str = Field(min_length=1, max_length=12_000_000)


class CharacterMergeRequest(BaseModel):
    target_character_id: int


class CharacterRead(BaseModel):
    id: int
    season_id: int
    name: str
    description: str
    aliases: list[str]
    color: str
    photo_count: int
    photo_urls: list[str]
    voice_sample_count: int
    narration_voice: str | None = None
    narration_voice_auto: str | None = None


class NarrationVoiceUpdate(BaseModel):
    narration_voice: str | None = Field(default=None, max_length=32)


class TtsVoiceRead(BaseModel):
    id: str
    label: str
    gender: str


class TtsVoiceCatalogRead(BaseModel):
    adapter: str
    voices: list[TtsVoiceRead]


class SpeakerIdentityUpdate(BaseModel):
    source_label: str = Field(min_length=1, max_length=64)
    character_id: int


class SpeakerIdentityRead(BaseModel):
    source_label: str
    character_id: int
    character_name: str
    confidence: float | None = None
    method: str


class SpeakerLabelsRead(BaseModel):
    labels: list[str]


class CharacterRecognitionResponse(BaseModel):
    analyzed_labels: int
    assigned_labels: int
    assignments: list[SpeakerIdentityRead]
    face_model: str
    voice_profiles_used: int


__all__ = [
    "CharacterCreate",
    "CharacterPhotoAdd",
    "CharacterMergeRequest",
    "CharacterRead",
    "NarrationVoiceUpdate",
    "TtsVoiceRead",
    "TtsVoiceCatalogRead",
    "SpeakerIdentityUpdate",
    "SpeakerIdentityRead",
    "SpeakerLabelsRead",
    "CharacterRecognitionResponse",
]
