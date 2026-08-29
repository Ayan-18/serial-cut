# SerialCuts Worklog

This file is the durable project memory for Codex sessions on the laptop and desktop. Update it after meaningful changes so a new task can continue without needing the full chat history.

## 2026-08-30 - Shared Codex Context

Added shared project context files:

- `AGENTS.md` for automatic Codex project guidance.
- `WORKLOG.md` as the running handoff log.
- `docs/CODEX_SYNC.md` with the laptop/desktop workflow.

Decision: GitHub is the source of truth for code and durable project memory. Codex chats themselves are useful working context, but the cross-computer handoff should live in committed files plus Git history.

## Current Product State

SerialCuts is an MVP local Windows app for Russian-dubbed TV episodes. It imports local seasons, analyzes episodes, proposes short vertical clips, lets the user review/edit candidates, renders MP4 exports, and can be controlled through a local UI or Telegram bot.

Implemented:

- FastAPI backend, SQLite, SQLAlchemy 2, Alembic.
- React + TypeScript + Vite frontend.
- Season import, fingerprint/dedupe, ffprobe metadata.
- Persistent job queue, recovery, pause/resume, run-next, cancel/retry, ETA.
- System check script.
- Stage 2 media pipeline: Russian audio/subtitle track selection, WAV extraction, proxy MP4, faster-whisper adapter + stub, PySceneDetect adapter + stub, transcript/word/scene persistence.
- Stage 3 candidate pipeline: local llama.cpp HTTP adapter + stub, strict Pydantic schemas, episode outline, candidate validation and dedupe.
- Stage 4 review/render/export: approve/reject, edited boundaries/crop, Russian SRT/ASS, FFmpeg 1080x1920 render, cover and metadata export.
- Stage 5 Telegram: long polling, whitelist, idempotent approve/reject/export callbacks.
- Product features: auto mode, persisted settings UI, season enqueue, YouTube Shorts / Instagram Reels render presets, NVENC detection, export with or without subtitles, optional two-pass loudnorm.

## Verification Snapshot

Last known checks from this project state:

- `.\.venv\Scripts\python.exe -m pytest`: passed, 32 tests.
- `npm run build`: passed.
- `.\scripts\check_system.ps1`: script works, but on the previous Codex environment it reported Python 3.10.4 and missing `ffmpeg` / `ffprobe`. Target machines should use Python 3.11+ and FFmpeg/ffprobe in `PATH`.

## Key Decisions

- Original media files are read-only and must never be modified, deleted, or uploaded.
- No external AI APIs for media, frames, audio, subtitles, transcripts, or analysis.
- No Docker in MVP.
- Heavy local adapters load lazily and have stubs for tests.
- FFmpeg commands are built as argument arrays, without shell execution.
- Derived outputs belong in cache/output directories, not next to original episodes unless explicitly configured.
- App settings may override product behavior but must not write secrets or mutate `.env`.

## Near-Term Next Steps

- Add a model installation assistant that shows model size and asks for confirmation before downloads.
- Add a persistent background queue loop option, while keeping `run-next` for testability.
- Improve crop UX with visual preview and keyframe thumbnails.
- Add candidate search/filtering in UI by score, status, episode, and reason.
- Add a safe cache cleanup screen that only deletes derived artifacts.
- Add import progress and richer diagnostics for common Windows setup problems.
- Add end-to-end smoke fixtures for a tiny local media sample.

## Useful Commands

```powershell
git pull --ff-only
Copy-Item .env.example .env
.\scripts\setup.ps1
.\scripts\check_system.ps1
.\scripts\run.ps1
.\.venv\Scripts\python.exe -m pytest
Push-Location frontend
npm run build
Pop-Location
```

## Remote

`git@github.com:Ayan-18/serial-cut.git`

