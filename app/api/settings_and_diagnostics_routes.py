from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api._shared import _cache_protected_paths, _ensure_no_active_jobs, _is_legacy_default_cache
from app.api.dependencies import get_session
from app.api.loopback import local_api_token
from app.api.schemas import CacheClearRequest, CacheRead, HealthRead, LocalApiTokenRead, LogTailRead, ModelCatalogEntryRead, ModelDiagnosticsRead, ModelInstallProgressRead, ModelInstallRequest, ProjectDiagnosticsRead, RuntimeSettingsRead, VersionRead
from app.application.cache import cache_summary, clear_cache, prepare_cache_directory
from app.application.model_diagnostics import check_models
from app.application.processing_guard import ProcessingBusyError
from app.application.project_diagnostics import run_project_diagnostics
from app.application.settings import RuntimeSettings, effective_settings, get_runtime_settings, save_runtime_settings
from app.application.system_check import report_as_dict, run_system_check
from app.infrastructure.config import get_settings
from app.application.log_reader import read_log_tail
from app.application.model_install import get_model_install_progress, model_catalog, start_model_install
from app.application.runtime_info import health_report, version_report

router = APIRouter(prefix="/api")

@router.get("/health", response_model=HealthRead)
def health(session: Session = Depends(get_session)):
    return health_report(session, local_api_token())


@router.get("/version", response_model=VersionRead)
def version() -> dict:
    return version_report()


@router.get("/logs", response_model=LogTailRead)
def logs(lines: int = 200, level: str | None = None, search: str | None = None):
    return read_log_tail(lines=lines, min_level=level, search=search)


@router.get("/security-token", response_model=LocalApiTokenRead)
def security_token() -> LocalApiTokenRead:
    return LocalApiTokenRead(token=local_api_token())


@router.get("/system-check")
def system_check() -> dict:
    return report_as_dict(run_system_check())


@router.get("/model-diagnostics", response_model=ModelDiagnosticsRead)
def model_diagnostics(session: Session = Depends(get_session)):
    return check_models(effective_settings(session, get_settings()))


@router.get("/model-catalog", response_model=list[ModelCatalogEntryRead])
def get_model_catalog():
    return model_catalog()


@router.post("/model-catalog/{key}/install", response_model=ModelInstallProgressRead)
def install_catalog_model(key: str, payload: ModelInstallRequest):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Подтвердите загрузку (confirm=true)")
    try:
        return start_model_install(key, confirm=payload.confirm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/model-catalog/{key}/install-progress", response_model=ModelInstallProgressRead)
def model_install_progress(key: str):
    return get_model_install_progress(key)


@router.get("/cache", response_model=CacheRead)
def read_cache(session: Session = Depends(get_session)):
    settings = effective_settings(session, get_settings())
    prepare_cache_directory(
        settings.cache_dir,
        protected_paths=_cache_protected_paths(session, settings.output_dir),
        allow_existing_unmarked=_is_legacy_default_cache(settings.cache_dir),
    )
    return cache_summary(settings.cache_dir)


@router.delete("/cache", response_model=CacheRead)
def delete_cache(payload: CacheClearRequest, session: Session = Depends(get_session)):
    try:
        _ensure_no_active_jobs(session, "Нельзя очищать кэш, пока есть активные или остановленные задачи")
        settings = effective_settings(session, get_settings())
        return clear_cache(
            settings.cache_dir,
            confirmed=payload.confirm,
            protected_paths=_cache_protected_paths(session, settings.output_dir),
        )
    except ProcessingBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/settings", response_model=RuntimeSettingsRead)
def read_settings(session: Session = Depends(get_session)):
    return get_runtime_settings(session, get_settings()).model_dump(mode="json")


@router.put("/settings", response_model=RuntimeSettingsRead)
def update_settings(payload: RuntimeSettings, session: Session = Depends(get_session)):
    try:
        current = get_runtime_settings(session, get_settings())
        if payload.cache_dir.expanduser().resolve(strict=False) != current.cache_dir.expanduser().resolve(strict=False):
            _ensure_no_active_jobs(session, "Нельзя менять кэш, пока есть активные или остановленные задачи")
        prepare_cache_directory(
            payload.cache_dir,
            protected_paths=_cache_protected_paths(session, payload.output_dir),
            allow_existing_unmarked=_is_legacy_default_cache(payload.cache_dir),
        )
        result = save_runtime_settings(session, payload)
        session.commit()
        return result.model_dump(mode="json")
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/project-diagnostics", response_model=ProjectDiagnosticsRead)
def project_diagnostics(session: Session = Depends(get_session)):
    return run_project_diagnostics(session, effective_settings(session, get_settings()))

