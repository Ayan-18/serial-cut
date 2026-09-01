from __future__ import annotations

from app.api._shared import *  # noqa: F403

router = APIRouter(prefix="/api")

@router.get("/exports", response_model=list[ExportRead])
def list_exports(session: Session = Depends(get_session)):
    return session.scalars(select(Export).order_by(Export.created_at.desc())).all()


@router.get("/exports/{export_id}/file")
def export_file(export_id: int, session: Session = Depends(get_session)):
    export = _get_export(session, export_id)
    path = Path(export.output_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл экспорта не найден")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/exports/{export_id}/cover")
def export_cover(export_id: int, session: Session = Depends(get_session)):
    export = _get_export(session, export_id)
    if not export.cover_path:
        raise HTTPException(status_code=404, detail="Обложка не создана")
    path = Path(export.cover_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл обложки не найден")
    return FileResponse(path, media_type="image/jpeg", filename=path.name)


@router.post("/exports/{export_id}/open-folder")
def open_export_folder(export_id: int, session: Session = Depends(get_session)):
    export = _get_export(session, export_id)
    path = Path(export.output_path).resolve(strict=False)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл экспорта не найден")
    try:
        os.startfile(path.parent)  # type: ignore[attr-defined]
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "folder": str(path.parent)}


@router.post("/episodes/{episode_id}/auto-export", response_model=AutoExportResponse)
def auto_export_episode(episode_id: int, payload: AutoExportRequest, session: Session = Depends(get_session)):
    settings = effective_settings(session, get_settings())
    try:
        _ensure_episode_not_enqueued(session, episode_id)
        session.commit()
        with processing_guard():
            result = auto_approve_and_export(
                session,
                episode_id,
                settings,
                threshold=payload.threshold if payload.threshold is not None else settings.auto_score_threshold,
                max_clips=payload.max_clips if payload.max_clips is not None else settings.max_clips_per_episode,
                use_nvenc=payload.use_nvenc if payload.use_nvenc is not None else settings.render_use_nvenc,
            )
        session.commit()
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result
