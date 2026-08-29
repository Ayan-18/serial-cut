# SerialCuts Worklog

This file is the durable project memory for Codex sessions on the laptop and desktop. Update it after meaningful changes so a new task can continue without needing the full chat history.

## 2026-08-30 - Visible Media Progress And Labeled Settings

Improved feedback and clarity in the React panel:

- Direct Stage 2 media analysis now immediately shows an animated status banner, episode name, and elapsed time.
- The active episode's Media/Candidates/Auto controls are disabled during processing to prevent duplicate or conflicting requests.
- Media errors are reported in the panel and controls are restored in a `finally` path.
- Settings are grouped into Files, Analysis and Auto, and Render sections.
- Every settings control now has a Russian label, units where relevant, and a short explanation.

Verification: frontend production build passed; the UI was inspected in the running local app; the timer advanced and cleared after Stage 2 completed; browser console contained no errors.

## 2026-08-30 - Empty Telegram Whitelist Setting

Fixed startup with the default `.env.example` value `SERIALCUTS_TELEGRAM_ALLOWED_USER_IDS=`. The field now bypasses automatic JSON decoding and uses the existing validator, so an empty value becomes an empty whitelist and comma-separated IDs remain supported.

Verification: `33 passed, 1 warning`; Alembic reached head; the FastAPI app imported successfully; every system-check item passed with the current `.env`.

## 2026-08-30 - Windows Environment Bootstrap

Installed and verified the local development prerequisites on this computer:

- Python 3.11.9 and a project-local `.venv` with dev dependencies.
- Node.js 24.19.0 with npm 11.17.0.
- FFmpeg/ffprobe 9.0.1.
- Existing NVIDIA GeForce GTX 1660 SUPER was detected successfully.

Fixed clean-install blockers discovered while running `scripts/setup.ps1`:

- Added explicit setuptools package discovery for `app*` so editable installs work.
- Made Alembic create the parent directory for a configured SQLite database.
- Made `scripts/setup.ps1` stop when a native setup command fails.
- Ignored generated `*.egg-info` directories.

Verification: backend tests passed (`32 passed, 1 warning`), frontend production build passed, and every system-check item passed. No ASR/LLM models were downloaded.

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

