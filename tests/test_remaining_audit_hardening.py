from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select

from app.api.loopback import _is_loopback_client
from app.application.cache import clear_cache, prepare_cache_directory
from app.application.candidate_editor import EditableSubtitle, save_candidate_subtitles
from app.application.derived_files import delete_derived_artifacts
from app.application.importer import import_season
from app.domain.enums import JobStatus
from app.infrastructure.config import Settings
from app.infrastructure.database import init_db, make_session_factory, require_migrated_database
from app.media.rendering import build_render_args
from app.models.base import Base
from app.models.entities import ClipCandidate, Episode, Export, Job, JobStage, Season
from app.workers.queue import (
    claim_next_queued_job,
    enqueue_episode_analysis,
    heartbeat_job_lease,
    recover_interrupted_jobs,
)
from app.workers.runner import run_next_job


def _episode(session, tmp_path: Path) -> int:
    season_dir = tmp_path / "season"
    season_dir.mkdir(exist_ok=True)
    source = season_dir / "episode.mkv"
    source.write_bytes(b"video")
    return import_season(session, season_dir).episode_ids[0]


def test_cache_requires_marker_and_never_deletes_protected_or_external_files(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "derived.bin").write_bytes(b"cache")
    original = tmp_path / "season" / "episode.mkv"
    original.parent.mkdir()
    original.write_bytes(b"original")

    with pytest.raises(ValueError, match="маркером"):
        clear_cache(cache_dir, confirmed=True)
    with pytest.raises(ValueError, match="защищённый"):
        prepare_cache_directory(tmp_path, protected_paths=[original], allow_existing_unmarked=True)

    prepare_cache_directory(cache_dir, protected_paths=[original], allow_existing_unmarked=True)
    clear_cache(cache_dir, confirmed=True, protected_paths=[original])
    assert original.read_bytes() == b"original"

    external = tmp_path / "outside.mp4"
    external.write_bytes(b"keep")
    derived = cache_dir / "preview.mp4"
    derived.write_bytes(b"remove")
    assert delete_derived_artifacts([external, derived], [cache_dir]) == [str(derived.resolve())]
    assert external.exists() and not derived.exists()


def test_render_command_maps_selected_audio_stream(tmp_path: Path):
    args = build_render_args(
        "ffmpeg",
        tmp_path / "episode.mkv",
        tmp_path / "clip.mp4",
        2,
        12,
        "center-crop",
        None,
        False,
        audio_stream_index=3,
    )
    maps = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "-map"]
    assert maps == ["0:v:0", "0:3"]


def test_queue_claim_is_atomic_and_recovers_only_expired_leases(tmp_path: Path):
    db_path = tmp_path / "queue.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as setup:
        episode_id = _episode(setup, tmp_path)
        first_job = enqueue_episode_analysis(setup, episode_id)
        setup.add(Job(kind="render_clip", status=JobStatus.QUEUED.value, payload={"candidate_id": 999}))
        setup.commit()
        first_job_id = first_job.id

    with factory() as first, factory() as second:
        claimed = claim_next_queued_job(first, "worker-one", lease_seconds=60)
        assert claimed is not None and claimed.id == first_job_id
        assert claim_next_queued_job(second, "worker-two", lease_seconds=60) is None
        assert heartbeat_job_lease(first, claimed.id, "worker-one", lease_seconds=90)
        lease_after_heartbeat = first.get(Job, claimed.id).lease_expires_at
        assert lease_after_heartbeat is not None
        assert recover_interrupted_jobs(second) == 0

        current = first.get(Job, claimed.id)
        current.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        first.commit()
        assert recover_interrupted_jobs(second) == 1
        second.commit()
        assert second.get(Job, claimed.id).status == JobStatus.QUEUED.value
    Base.metadata.drop_all(engine)


def test_worker_records_failure_after_rollback(session, tmp_path: Path):
    episode_id = _episode(session, tmp_path)
    job = enqueue_episode_analysis(session, episode_id)
    session.commit()
    existing_season = session.get(Episode, episode_id).season
    called: list[bool] = []

    def broken_stage(db, *_args):
        called.append(True)
        db.add(Season(title="Дубликат", root_path=existing_season.root_path))
        db.flush()

    result = run_next_job(
        session,
        Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"),
        stage2_func=broken_stage,
        stage3_func=lambda *_args: None,
    )

    session.expire_all()
    stored = session.get(Job, job.id)
    stage = session.scalar(select(JobStage).where(JobStage.job_id == job.id))
    assert called
    assert result.status == JobStatus.FAILED.value
    assert stored is not None and stored.status == JobStatus.FAILED.value
    assert stored.worker_id is None and stored.lease_expires_at is None
    assert stage is not None and stage.status == JobStatus.FAILED.value


def test_subtitle_change_marks_old_exports_stale(session, tmp_path: Path):
    episode_id = _episode(session, tmp_path)
    candidate = ClipCandidate(
        episode_id=episode_id,
        start_time=0,
        end_time=20,
        title="Сцена",
        description="Описание",
        moment_type="диалог",
        score=80,
        scores_json={},
        rationale="Понятно",
        problems_json=[],
        status="rendered",
    )
    session.add(candidate)
    session.flush()
    old_export = Export(candidate_id=candidate.id, output_path=str(tmp_path / "old.mp4"))
    session.add(old_export)
    session.flush()

    save_candidate_subtitles(
        session,
        candidate.id,
        [EditableSubtitle(None, 0, 3, "Новый полный текст")],
    )

    assert candidate.edit_revision == 1
    assert candidate.status == "approved"
    assert old_export.status == "stale"


def test_startup_requires_alembic_and_network_is_loopback_only():
    engine = create_engine("sqlite:///:memory:", future=True)
    init_db(engine)
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        require_migrated_database(engine)
    with pytest.raises(ValidationError, match="localhost/loopback"):
        Settings(app_host="0.0.0.0")
    assert _is_loopback_client({"client": ("127.0.0.1", 1000)})
    assert _is_loopback_client({"client": ("testclient", 1000)})
    assert not _is_loopback_client({"client": ("192.168.1.20", 1000)})
