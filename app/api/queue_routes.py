from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.api.schemas import (
    JobRead,
    JobStageRead,
    JobStageRetryRequest,
    QueueDataRead,
    QueueRunResponse,
    QueueStateResponse,
)
from app.application.queue_control import get_queue_state, set_queue_paused
from app.application.settings import effective_settings
from app.infrastructure.config import get_settings
from app.models.entities import Job, JobStage
from app.workers.queue import (
    JobBusyError,
    delete_job,
    queue_snapshot,
    recover_interrupted_jobs,
    request_cancel,
    retry_job,
    retry_job_from_stage,
)
from app.workers.runner import estimate_eta_seconds, run_next_job


router = APIRouter(prefix="/api", tags=["queue"])


@router.post("/jobs/recover")
def recover_jobs(session: Session = Depends(get_session)) -> dict[str, int]:
    count = recover_interrupted_jobs(session)
    session.commit()
    return {"recovered": count}


@router.post("/queue/run-next", response_model=QueueRunResponse)
def run_queue_next(session: Session = Depends(get_session)):
    result = run_next_job(session, effective_settings(session, get_settings()))
    session.commit()
    return result


@router.post("/queue/pause", response_model=QueueStateResponse)
def pause_queue(session: Session = Depends(get_session)):
    state = set_queue_paused(session, True)
    session.commit()
    return {"state": state}


@router.post("/queue/resume", response_model=QueueStateResponse)
def resume_queue(session: Session = Depends(get_session)):
    state = set_queue_paused(session, False)
    session.commit()
    return {"state": state}


@router.post("/jobs/{job_id}/cancel", response_model=JobRead)
def cancel_job(job_id: int, session: Session = Depends(get_session)):
    job = request_cancel(session, job_id)
    session.commit()
    return job


@router.post("/jobs/{job_id}/retry", response_model=JobRead)
def retry_job_endpoint(job_id: int, session: Session = Depends(get_session)):
    job = retry_job(session, job_id)
    session.commit()
    return job


@router.post("/jobs/{job_id}/retry-stage", response_model=JobRead)
def retry_job_from_stage_endpoint(
    job_id: int,
    payload: JobStageRetryRequest,
    session: Session = Depends(get_session),
):
    try:
        job = retry_job_from_stage(session, job_id, payload.stage_name)
        session.commit()
        return job
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/jobs/{job_id}")
def delete_job_endpoint(job_id: int, session: Session = Depends(get_session)):
    try:
        delete_job(session, job_id)
        session.commit()
    except JobBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": True}


def build_queue_data(session: Session) -> QueueDataRead:
    """Shared queue+jobs payload used by GET /api/jobs and the SSE stream."""
    snapshot = queue_snapshot(session)
    items = session.scalars(select(Job).order_by(Job.updated_at.desc())).all()
    return QueueDataRead.model_validate(
        {
            "snapshot": {
                "queued": snapshot.queued,
                "running": snapshot.running,
                "failed": snapshot.failed,
                "paused": get_queue_state(session) == "paused",
                "eta_seconds": estimate_eta_seconds(session),
            },
            "items": items,
        }
    )


@router.get("/jobs", response_model=QueueDataRead)
def jobs(session: Session = Depends(get_session)):
    return build_queue_data(session)


@router.get("/jobs/{job_id}/stages", response_model=list[JobStageRead])
def job_stages(job_id: int, session: Session = Depends(get_session)):
    if session.get(Job, job_id) is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return session.scalars(
        select(JobStage).where(JobStage.job_id == job_id).order_by(JobStage.id)
    ).all()
