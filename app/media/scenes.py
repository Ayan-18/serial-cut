from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Callable, Protocol

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.infrastructure.processes import ProcessCancelledError
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
    def __init__(
        self,
        min_scene_len: int = 15,
        progress_callback: Callable[[float, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.min_scene_len = min_scene_len
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check

    def detect(self, proxy_path: Path) -> list[SceneInterval]:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import AdaptiveDetector

        video = open_video(str(proxy_path))
        scene_manager = SceneManager()
        scene_manager.add_detector(AdaptiveDetector(min_scene_len=self.min_scene_len))
        finished = Event()
        cancelled = Event()

        def monitor() -> None:
            while not finished.wait(0.35):
                if self.cancel_check is not None and self.cancel_check():
                    cancelled.set()
                    scene_manager.stop()
                    return

        def report_scene(_frame, _scene_count: int) -> None:
            # PySceneDetect invokes this callback in its detection thread, so the
            # SQLAlchemy-backed job progress callback remains single-threaded.
            if self.progress_callback is None:
                return
            try:
                current = float(video.position.get_seconds())
                duration = max(0.1, float(video.duration.get_seconds()))
                self.progress_callback(
                    min(0.99, current / duration),
                    f"Сцены: просмотрено {current:.0f} из {duration:.0f} сек",
                )
            except (AttributeError, TypeError, ValueError):
                pass

        watcher = Thread(target=monitor, name="serialcuts-scene-progress", daemon=True)
        watcher.start()
        try:
            scene_manager.detect_scenes(video, callback=report_scene)
        finally:
            finished.set()
            watcher.join(timeout=1)
        if cancelled.is_set():
            raise ProcessCancelledError("Поиск сцен остановлен пользователем")
        if self.progress_callback is not None:
            self.progress_callback(1.0, "Сцены найдены")
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
