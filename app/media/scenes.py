from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.entities import Scene


@dataclass(frozen=True)
class SceneInterval:
    start_time: float
    end_time: float
    confidence: float | None = None
    metadata: dict | None = None


class SceneDetector(Protocol):
    def detect(self, proxy_path: Path) -> list[SceneInterval]:
        ...


class StubSceneDetector:
    def detect(self, proxy_path: Path) -> list[SceneInterval]:
        return [SceneInterval(0.0, 4.0, confidence=1.0, metadata={"adapter": "stub"})]


class PySceneDetectAdapter:
    def __init__(self, min_scene_len: int = 15) -> None:
        self.min_scene_len = min_scene_len

    def detect(self, proxy_path: Path) -> list[SceneInterval]:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import AdaptiveDetector

        video = open_video(str(proxy_path))
        scene_manager = SceneManager()
        scene_manager.add_detector(AdaptiveDetector(min_scene_len=self.min_scene_len))
        scene_manager.detect_scenes(video)
        intervals: list[SceneInterval] = []
        for start, end in scene_manager.get_scene_list():
            intervals.append(
                SceneInterval(
                    start_time=float(start.get_seconds()),
                    end_time=float(end.get_seconds()),
                    metadata={"adapter": "pyscenedetect", "detector": "AdaptiveDetector"},
                )
            )
        return intervals


def save_scenes(session: Session, episode_id: int, intervals: list[SceneInterval]) -> int:
    session.flush()
    session.execute(delete(Scene).where(Scene.episode_id == episode_id))
    for interval in intervals:
        session.add(
            Scene(
                episode_id=episode_id,
                start_time=interval.start_time,
                end_time=interval.end_time,
                confidence=interval.confidence,
                metadata_json=interval.metadata,
            )
        )
    return len(intervals)
