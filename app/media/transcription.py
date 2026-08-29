from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import TranscriptSegment, WordTimestamp


@dataclass(frozen=True)
class Word:
    start_time: float
    end_time: float
    word: str


@dataclass(frozen=True)
class TranscriptChunk:
    start_time: float
    end_time: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass(frozen=True)
class TranscriptResult:
    language: str
    segments: list[TranscriptChunk]


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> TranscriptResult:
        ...


class StubTranscriber:
    def transcribe(self, audio_path: Path) -> TranscriptResult:
        return TranscriptResult(
            language="ru",
            segments=[
                TranscriptChunk(
                    start_time=0.0,
                    end_time=4.0,
                    text="Синтетическая русская реплика для проверки конвейера.",
                    words=[
                        Word(0.0, 0.5, "Синтетическая"),
                        Word(0.6, 1.0, "русская"),
                        Word(1.1, 1.6, "реплика"),
                        Word(1.7, 2.0, "для"),
                        Word(2.1, 2.7, "проверки"),
                        Word(2.8, 3.6, "конвейера"),
                    ],
                )
            ],
        )


class FasterWhisperTranscriber:
    def __init__(
        self,
        model_name: str,
        compute_type: str,
        fallback_compute_type: str,
        device: str = "auto",
        language: str = "ru",
    ) -> None:
        self.model_name = model_name
        self.compute_type = compute_type
        self.fallback_compute_type = fallback_compute_type
        self.device = device
        self.language = language

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        last_error: RuntimeError | None = None
        for device, compute_type in self._attempts():
            try:
                return self._transcribe_with(device, compute_type, audio_path)
            except RuntimeError as exc:
                last_error = exc
        raise RuntimeError("Не удалось запустить faster-whisper на CUDA или CPU") from last_error

    def _attempts(self) -> list[tuple[str, str]]:
        if self.device == "cpu":
            return [("cpu", "int8")]
        attempts = [(self.device, self.compute_type)]
        if self.fallback_compute_type != self.compute_type:
            attempts.append((self.device, self.fallback_compute_type))
        if self.device == "auto":
            attempts = [("cuda", compute_type) for _, compute_type in attempts]
            attempts.append(("cpu", "int8"))
        return list(dict.fromkeys(attempts))

    def _transcribe_with(self, device: str, compute_type: str, audio_path: Path) -> TranscriptResult:
        from faster_whisper import WhisperModel

        model = WhisperModel(self.model_name, device=device, compute_type=compute_type)
        segments, info = model.transcribe(
            str(audio_path),
            language=self.language,
            word_timestamps=True,
            vad_filter=True,
        )
        chunks: list[TranscriptChunk] = []
        for segment in segments:
            words = [
                Word(float(word.start), float(word.end), word.word.strip())
                for word in (segment.words or [])
                if word.word.strip()
            ]
            chunks.append(
                TranscriptChunk(
                    start_time=float(segment.start),
                    end_time=float(segment.end),
                    text=segment.text.strip(),
                    words=words,
                )
            )
        return TranscriptResult(language=getattr(info, "language", self.language), segments=chunks)


def save_transcript(session: Session, episode_id: int, result: TranscriptResult) -> int:
    session.flush()
    existing_ids = session.scalars(
        select(TranscriptSegment.id).where(TranscriptSegment.episode_id == episode_id)
    ).all()
    if existing_ids:
        session.execute(delete(WordTimestamp).where(WordTimestamp.segment_id.in_(existing_ids)))
    session.execute(delete(TranscriptSegment).where(TranscriptSegment.episode_id == episode_id))
    count = 0
    for chunk in result.segments:
        segment = TranscriptSegment(
            episode_id=episode_id,
            start_time=chunk.start_time,
            end_time=chunk.end_time,
            text=chunk.text,
        )
        session.add(segment)
        session.flush()
        for word in chunk.words:
            session.add(
                WordTimestamp(
                    segment_id=segment.id,
                    start_time=word.start_time,
                    end_time=word.end_time,
                    word=word.word,
                )
            )
        count += 1
    return count
