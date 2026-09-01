# SerialCuts Agent Guide

## Project Identity

SerialCuts is a local Windows-first app for analyzing Russian-dubbed TV episodes and exporting vertical clips for YouTube Shorts / Instagram Reels.

The product promise is privacy-first local processing:

- Do not upload original media, audio, frames, subtitles, or transcripts to external AI services.
- Do not modify, delete, or overwrite original episode files.
- Keep Docker out of the MVP unless the user explicitly changes this decision.
- Prefer local adapters: FFmpeg/ffprobe, faster-whisper, PySceneDetect, llama.cpp HTTP on `127.0.0.1`, and deterministic stubs for tests.

## Current Architecture

- Backend: FastAPI, SQLAlchemy 2, SQLite, Alembic.
- Frontend: React + TypeScript + Vite.
- Queue: persistent SQLite job queue with explicit run-next, pause/resume, cancel/retry, recovery.
- Media pipeline:
  - Stage 1: import season, fingerprint/dedupe, ffprobe, queue, system check.
  - Stage 2: Russian track selection, WAV extraction, proxy MP4, ASR, scene detection.
  - Stage 3: episode outline, local LLM candidate generation, strict JSON validation.
  - Stage 4: review, SRT/ASS subtitles, render/export.
  - Stage 5: Telegram long polling adapter with whitelist and idempotent callbacks.
- Product features already added: auto mode, persisted UI settings, season enqueue, queue controls, ETA, render presets, NVENC detection, export with/without subtitles, optional two-pass loudnorm.
- Operability: `/api/health` + `/api/version` + `/api/logs`, in-UI log viewer, `/api/model-catalog` with in-app face-model install, candidate edit history/undo (`CandidateEditSnapshot`, migration 0014), batch candidate review/render, keyframe-thumbnail crop strip, generated `docs/API.md` (`scripts/dump_openapi.py`), `resolve_within` path guard on file endpoints, `scripts/bootstrap.ps1`.
- After adding or changing an endpoint, run `scripts/dump_openapi.py` and commit `docs/`.
- StoryArc narration TTS is pluggable (`app/media/tts.py`): default `silero` (local neural, needs `.[tts]` extra + `data/models/tts/v4_ru.pt`), plus `windows-sapi` and `stub`. Per-character voice via `Character.narration_voice` (migration 0015) or auto by gender. Synthetic voice only — never actor cloning.

## Important Files

- `README.md` is the user-facing setup and feature overview.
- `ARCHITECTURE.md` is the system map.
- `MODEL_SETUP.md` documents local model choices and environment variables.
- `WORKLOG.md` is the durable handoff log between Codex tasks and computers.
- `docs/CODEX_SYNC.md` explains the laptop/desktop sync workflow.

## Development Rules

- Read the relevant files before editing; follow existing patterns.
- Use `rg` / `rg --files` first when searching.
- Keep changes small and aligned with the current architecture.
- Use `apply_patch` for manual edits.
- Never revert user changes unless the user explicitly asks.
- Never commit `.env`, `.venv`, `data`, model files, media files, caches, or generated frontend/backend outputs.
- If a change touches behavior, add or update focused tests.
- For frontend work, run `npm run build`.
- For backend work, run `.\.venv\Scripts\python.exe -m pytest` when the venv exists.
- If system dependencies are relevant, run `.\scripts\check_system.ps1` and report missing Python/FFmpeg/NVIDIA tools clearly.

## Sync Protocol For Every Codex Task

Before substantial work:

1. Check `git status --short --branch`.
2. Pull the latest `main` if the user wants work synchronized with GitHub.
3. Read `WORKLOG.md`, `README.md`, and the specific files for the task.

After substantial work:

1. Update `WORKLOG.md` with date, summary, tests, decisions, and next steps.
2. Run the relevant verification commands.
3. Commit with a clear message.
4. Push to `origin/main` when the user asks to sync both computers.

## Current Remote

Repository: `git@github.com:Ayan-18/serial-cut.git`

