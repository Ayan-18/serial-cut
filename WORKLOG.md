# SerialCuts Worklog

This file is the durable project memory for Codex sessions on the laptop and desktop. Update it after meaningful changes so a new task can continue without needing the full chat history.

## 2026-08-31 - Season Workflow Tools

Implemented the requested 10-point product pass without changing the launcher:

- StoryArc render can now be queued with `render_story_arc` jobs.
- StoryArc plans can be edited: metadata, segment order, timing, title, role, delete/add candidate.
- Added video script drafts tied to a season or StoryArc.
- Added local Windows TTS narration export to WAV from StoryArc narration text.
- StoryArc render accepts `cut` or `fade` transition style; fade adds short in/out fades per segment.
- Added global season search across candidates and transcript rows.
- Added publishing plan drafts with platform, title, description, hashtags and optional schedule.
- Quality benchmark now has a character-arc recap-vs-turn case and filters weak auto-selected candidates.
- Added project diagnostics for DB counts, missing media paths, failed jobs, StoryArc consistency and cache/output dirs.
- Added `scripts/create_demo_sample.ps1` to generate a tiny FFmpeg demo season.

Verification: targeted backend tests passed (`11 passed`), frontend production build passed,
quality benchmark passed. Full test suite was not run in this local venv because `numpy` is not
installed; API/worker imports were made lazy so the app can still start far enough to show
diagnostics before heavy media packages are installed.

## 2026-08-31 - StoryArc Multi-Source Render

Implemented the first render/export path for saved multi-episode story arcs:

- Added `StoryArcExport` model plus Alembic revision `0008_story_arc_exports`.
- Added `app/application/story_arc_render.py`.
- `render_story_arc` renders each `StoryArcSegment` through the existing vertical `render_clip`
  pipeline, then uses FFmpeg concat demuxer to produce one MP4 from different episode files.
- StoryArc exports write metadata with source episodes, candidate ids, ranges, roles and the
  generated narration/script lines.
- Added API endpoints:
  - `POST /api/story-arcs/{id}/render`
  - `GET /api/story-arc-exports/{id}/file`
  - `GET /api/story-arc-exports/{id}/cover`
- The React `Сюжетные видео` section can render a plan with or without subtitles and shows the
  latest StoryArc MP4 inline.
- Character-based story arcs now include a draft first-person narration plan in `plan_json.narration`
  and display it in the UI. This is script text only; local TTS voiceover is not implemented yet.

Decision: StoryArc render is synchronous for now to keep the first implementation small and
testable. Moving it into the background queue is the next ergonomic improvement before rendering
large long-form videos.

Verification on the laptop: focused StoryArc/render tests passed (`20 passed`), Alembic upgraded to
`0008_story_arc_exports`, and the frontend production build passed.

## 2026-08-31 - Season Story Arc Planning

Added the first repository-backed layer for multi-episode and future long-form videos:

- Added `StoryArc` and `StoryArcSegment` models plus Alembic revision `0007_story_arcs`.
- Added `app/application/story_arcs.py`, a deterministic planner that builds an editable montage
  plan from already-generated candidates across a whole season.
- Story arc plans support `single_short`, `shorts_series`, `story_video` and `long_video` formats,
  optional prompt matching, optional target character priority and max segment/duration limits.
- Added API endpoints to list, create, read, rebuild and delete story arcs.
- Added a React `Сюжетные видео` workspace with season/format/character/request controls and a
  saved montage-plan list. Each segment can jump back to its original candidate for review.
- Added focused tests for multi-episode planning and character-prioritized arc selection.

Decision: this commit deliberately adds the planning layer before multi-source FFmpeg concatenation.
The next safe step is render/export for a saved `StoryArc`, including per-segment subtitles,
loudness normalization and optional separators/transitions.

Verification on the laptop: focused backend tests passed (`23 passed`), Python compile passed for the
changed modules, and the frontend production build passed.

## 2026-08-31 - Quality And Usability Pass

Improved the existing quality-critical product functions without touching the one-click launcher:

- Candidate scoring v2 now considers standalone clarity, payoff, emotion, long pauses, weak endings,
  recap/credits markers and speech-cut problems more strongly.
- Added `app/application/quality_report.py` plus API endpoints for per-episode and per-candidate
  quality summaries and recommendations.
- Added candidate edit saving via `PATCH /api/candidates/{id}` so preview can persist boundaries/crop
  without marking the candidate approved.
- Added fast preview rendering: `POST /api/candidates/{id}/preview` creates a 540x960 MP4 in cache,
  and `GET /api/candidates/{id}/preview-file` serves it.
- Render crop filters now use preset dimensions instead of hard-coded 1080x1920, and auto-follow
  keyframes are smoothed before saving/rendering.
- Added subtitle QA and auto-split for long/fast/overlapping subtitle rows.
- Queue stages now record failed stage errors, and `GET /api/jobs/{id}/stages` exposes the timeline.
- Added duplicate character merge support that moves photos/aliases/speaker identities into the
  target profile.
- React UI now has candidate search, filters, score breakdown, quality recommendations, preview MP4,
  subtitle warnings/autosplit, job timelines and character merge controls.

Verification on the laptop: focused scoring/benchmark tests passed (`5 passed`), quality benchmark
passed with average `77/100`, Python compile passed for changed pure modules, and frontend production
build passed. Full backend suite could not run on the laptop because its local `.venv` is Python
3.10.4 and lacks `numpy`; the project requires Python 3.11+ and the main PC has the proper runtime.

## 2026-08-31 - Quality Benchmark

Added a lightweight repository-shared quality benchmark instead of changing the one-click launcher:

- `app/analysis/benchmark.py` loads JSON quality cases, runs boundary adjustment, candidate
  calibration and dedupe, then reports candidate quality, boundary quality, expected-scene coverage,
  precision, duplicate rate and invalid clips.
- `tests/quality/story_dialogue.json` provides a video-free fixture with transcript segments,
  scenes, candidate proposals and expected good ranges.
- `scripts/quality_check.ps1` runs the benchmark from PowerShell using the project venv when present.
- `tests/test_quality_benchmark.py` covers the scoring gate, text report and JSON-serializable result.

Decision: quality work should be measurable before changing the main candidate-generation algorithm.
The benchmark must stay lightweight and commit-friendly: no original media, rendered clips, model
files or cache artifacts in Git.

## 2026-08-31 - Multimodal Character Identity And Active-Speaker Crop

Completed the five requested identity and framing features:

- Replaced the primary face path with local OpenCV Zoo YuNet + SFace. The official ONNX files are
  downloaded by a dedicated confirmation script, verified against pinned SHA-256 values and kept in
  ignored `data/models/face`; Haar/DCT remains only as an explicit fallback.
- Character cards now accept up to eight photos per selection, show all saved angles, and can add or
  remove individual local copies without touching the user's originals.
- Added lip-motion analysis over the detected mouth region. Speaker-cluster recognition samples the
  face whose mouth changes during each transcript segment instead of assuming the largest face talks.
- Added persistent local spectral voiceprints. A manual speaker mapping trains the character profile;
  conservative automatic matching can reuse it in later episodes and fuses agreeing face/lip/voice
  evidence while rejecting conflicts.
- Auto-follow crop now prefers the known character assigned to the active transcript segment, then
  lip motion, then the largest face. The API reports how many points came from identity or lips.
- Added Alembic revision `0006_multimodal_character_identity`, model diagnostics and focused tests.

Verification: the live and a clean database migrated to 0006; official model checksums passed; the
real episode proxy was read-only sampled with YuNet + SFace (22 face detections in six frames) and
lip-motion selection executed. Backend tests passed (`56 passed, 1 upstream warning`), the frontend
production build passed, and every system check succeeded. Original
media and existing exports were not modified.

## 2026-08-30 - Story Packs, Characters And Complete Boundaries

Implemented the first complete narrative-quality pass requested after reviewing a real clip that
ended halfway through a spoken sentence:

- Candidate duration caps now choose a completed transcript segment instead of blindly truncating at
  the configured second limit; the quality pass explicitly detects start/end cuts inside speech.
- Added editable season/episode context, required/excluded events, spoiler preference, the existing
  highlight mode and a new chronological `story` mode. Stage 3 gives this context plus the outline to
  local Qwen and stores part order, narrative role and continuity notes.
- Added an outline viewer and a workflow to save context and regenerate candidates from the episode
  workspace.
- Added a local character library with name, description and copied reference photos under the
  ignored `data/characters` directory. Voice clusters can be mapped manually or conservatively
  suggested from reference faces; ambiguous matches remain unassigned.
- Speaker fields are character dropdowns. An optional render setting burns the confirmed character
  name above the subtitle without changing the original transcript.
- `Найти лица` now samples a trajectory, median-filters and rate-limits horizontal movement, and
  stores keyframes used by a time-based FFmpeg crop expression and the UI preview.
- Added Alembic revision `0005_story_context_and_characters` and focused tests for complete speech
  boundaries, story mode, local character photos, speaker-name rendering and dynamic crop filters.

Verification: backend suite passed (`54 passed, 1 upstream warning`), the frontend production build
passed, and a clean database migrated from revision 0001 through 0005. The live database recovered
from a partially pre-created-table state, reached 0005 and the restarted app served health, context,
character and existing-candidate data. Browser inspection confirmed the new panels and story-mode
switch with no console errors. A generated dynamic crop expression also passed a real FFmpeg parse.

## 2026-08-30 - SQLite Concurrency Guard

Fixed `sqlite3.OperationalError: database is locked` reproduced when a manual Stage 2 request was
started while the background queue was already analyzing the same episode:

- Added one process-wide guard for heavy Stage 2, Stage 3, face analysis, synchronous render and
  auto-export operations; a conflicting API request now returns HTTP 409 with a clear explanation.
- Manual analysis/export controls are disabled for episodes with queued/running/paused jobs, and
  candidate write/render controls are disabled while their episode is active.
- Released database transactions before running Whisper, Qwen, scene detection and FFmpeg, then
  committed each restartable stage in a short transaction.
- Configured SQLite connections with a 30-second busy timeout and WAL journal mode. If an older
  running process temporarily prevents the WAL switch, startup continues and the next idle
  connection enables it.
- Added focused tests for the heavy-operation guard, WAL/busy timeout and the absence of an open
  transaction while ASR runs.

Verification: backend suite passed (`47 passed, 1 upstream warning`), the frontend production
build passed, and the system check found Python 3.11, FFmpeg/ffprobe, NVIDIA and sufficient free
space. The original media files were not modified.

## 2026-08-30 - Full Review, Background Queue And Export Workspace

Implemented the complete requested product feature pass:

- Added a persistent automatic background worker for episode analysis and clip rendering, with
  startup recovery, visible stage/progress, pause/resume, cancel and retry.
- Added a vertical range preview, candidate status filters/sorting, editable boundaries, visual crop
  offset/zoom, and local OpenCV face-centering.
- Added a per-candidate subtitle editor for text/timing/speaker labels. Original transcript rows stay
  unchanged; manual subtitle rows are stored separately and used for rendering.
- Added local heuristic speaker clustering, deterministic audio/visual/boundary score calibration,
  sentence-aware boundary adjustment and cross-episode transcript dedupe.
- Added an export gallery with video/cover endpoints and Windows folder opening, local model
  diagnostics, and confirmed cache-only cleanup with path containment checks.
- Added `Start SerialCuts.cmd`, a shortcut creation script, and created `SerialCuts.lnk` on this
  computer's desktop.
- Added migration `0004_product_workflow`, including recovery from partially pre-created SQLAlchemy
  tables, and documented the updated architecture and API.

Verification: Alembic reached `0004_product_workflow (head)` after exercising the partial-upgrade
recovery path; backend suite passed (`45 passed, 1 upstream warning`); frontend production build
passed. The UI was opened against the current database: 5 candidates, editable word-timed subtitle
rows, model readiness, cache size and 2 existing exports rendered correctly. Original media and
existing exports were not modified during these checks.

## 2026-08-30 - Subtitle Timing, Sizing And Render Fallback

Fixed the first real exported clip after visual inspection:

- Subtitle pages no longer share identical timestamps and overlap; rendering now uses saved word
  timestamps so every recognized word appears sequentially.
- ASS files declare `PlayResX: 1080` / `PlayResY: 1920`, use a smaller default font size of 48,
  preserve a two-line limit, and expose font size in the UI settings.
- UI renders now intentionally rebuild an existing derived export so subtitle/style changes apply.
- FFmpeg automatically retries with CPU `libx264` when NVENC is present but the installed NVIDIA
  driver is too old for the encoder API.
- Candidate analysis now has an elapsed timer, spinner, disabled conflicting controls, and visible
  error reporting. The familiar `scripts/run.ps1` delegates to the full local-model launcher when
  `.env` enables llama.cpp.

Verification: the existing 35-second candidate was regenerated at 1080x1920 with 13 sequential ASS
cues; a rendered frame was visually inspected and showed two readable subtitle lines. Focused backend
tests and the full suite passed (`41 passed, 1 upstream warning`), the frontend production build passed,
and every system check passed. The new subtitle-size setting loaded as 48 in the running UI with no
browser console errors.

## 2026-08-30 - Real Local Models And One-Command Launch

Enabled the complete privacy-first local pipeline on this computer:

- Installed official llama.cpp and downloaded pinned `faster-whisper-small` plus verified
  `Qwen3-4B-Q4_K_M.gguf` under ignored `data/models` (about 3 GB total).
- Added an explicit-confirmation model installer with a fixed Qwen SHA-256.
- Added CPU `int8` ASR plus CUDA-to-CPU fallback and configured this machine for reliable CPU ASR.
- Migrated the llama.cpp adapter to local `/v1/chat/completions`, disabled Qwen thinking, and added
  strict structured output validation.
- Made the episode outline deterministic from transcript timestamps so a verbose 4B model cannot
  block candidate analysis.
- Split candidate generation into three episode sections and enforce the configured 35-59 second
  range, which prevents first-minute-only and too-short results.
- Kept adapter/model connection settings owned by `.env`, so stale persisted UI values cannot
  silently switch real processing back to stubs.
- Added `scripts/run_local.ps1` to start and stop the local Qwen server with the app and keep its
  logs under `data/logs`.

Real verification: full Stage 2 on an 11:42 episode produced 137 transcript segments and 194 scenes
in roughly 3-4 minutes. Real Stage 3 completed in about 53 seconds and produced 5 candidates spread
across the episode at 35-59 seconds each. The one-command launcher started both health endpoints and
cleanly stopped its owned LLM process. Backend verification passed (`38 passed, 1 upstream warning`),
the frontend production build passed, and every system check passed. Original media remained read-only
and no content was uploaded.

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

