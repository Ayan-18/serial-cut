# SerialCuts Worklog

## 2026-09-04 - E2E simulation, face tracking and silent-failure hardening

A full run of the real app (synthetic 3-episode season, stub ASR/LLM/TTS, real FFmpeg,
YuNet/SFace weights installed) end to end: import -> analyze -> candidates ->
keyframes/history/edit -> batch review -> render -> StoryArc -> narration -> publishing.json ->
deletion. 50 automated API checks, all green after the fixes below.

Live bugs found by the run:

- `GET /api/jobs` returned HTTP 400 ("Unable to serialize unknown type: Job") - it returned raw
  ORM rows with no `response_model`, so the whole queue panel was dead. Added `QueueDataRead` /
  `QueueSnapshotRead` + an integration test.
- `extract_audio` / `create_proxy` surfaced a bare `WinError 3` when FFmpeg exited 0 without
  writing the file (long path / MAX_PATH). Now a clear message pointing at the cache path and the
  Windows long-path setting.

Face tracking — «трекинг по лицу не работает, просто центрирует»:

- Root cause: OpenCV 5 dropped `cv2.CascadeClassifier` and the YuNet/SFace weights were not
  installed, so `estimate_face_offset` found no faces, produced no trajectory, and `_crop_filter`
  silently degraded auto-follow to a constant centre crop.
- `LocalFaceRecognizer.can_detect`; `estimate_face_offset` returns
  `face_detection_available=False` early. `POST /api/candidates/{id}/auto-crop` returns HTTP 422
  with an install hint (route body moved to `app/application/auto_crop.py`).
- Picking "По лицам" in the crop dropdown runs the tracker (`chooseCrop`) - the option always
  means "tracked", never "centred".
- `_apply_candidate_edits` keeps the auto-follow trajectory across pure offset/scale tweaks.
- auto-crop tracks on the source, not the ~640px proxy (1 face detection vs 24 on the same clip).
- Verified with real YuNet: a face crossing the frame yields a -0.53 -> +0.48 trajectory and the
  rendered vertical clip pans to follow.

Silent-degradation audit - every feature reviewed for the same class (gated on a missing
model/dep, silently no-ops without telling the user):

- `identify-characters` - the UI message distinguishes "no «Говорящий N» labels - run media
  analysis first" and "no YuNet/SFace / check photos" from a plain "no matches".
- Windows SAPI narration errors out when Windows has no ru-RU voice instead of reading Russian
  text with an English voice.
- Narration text carries a `source` flag (`llm` / `template` / `manual`, stored in
  `plan_json.narration_source`); the arc card and the WAV action say "заглушка (Qwen недоступна)"
  for templated text.
- `select_cover_timestamp` uses YuNet when the model is present (was relying on the dead Haar
  path); sharpness/brightness only without it.
- Any pipeline stage result with a `.warnings` list is surfaced by `_run_stage` on the completed
  `JobStage` note and `job.progress_message` - covers stage-2 speaker-clustering failures and
  two-pass loudnorm dropping to single-pass. `EpisodeQualityReport.media_warnings` + the
  candidate-panel quality strip.

Also this session:

- `LoopbackOnlyMiddleware` Host-header allowlist (`_has_allowed_host`) - closes the DNS-rebinding
  gap where an attacker page resolving its domain to 127.0.0.1 would look same-origin.
- Flat-config ESLint 10 (typescript-eslint, react-hooks, react-refresh) + a `typecheck` script,
  both wired into the frontend CI job. 18 unused names pruned from the `AppView` destructure.

Verification: `pytest` 178 passed; `ruff` + `mypy` (102 files) clean; `npm run lint` / `typecheck`
/ `build` / `test` (10) clean; 50/50 end-to-end API checks green. YuNet/SFace weights were
installed on this laptop to verify tracking - `data/` is gitignored.


## 2026-09-03 - Fix ctranslate2 pkg_resources crash, pin torch

- `ctranslate2 4.6.0` → `4.6.3`. On Windows `ctranslate2/__init__.py` located its DLL folder via
  `pkg_resources`, which `setuptools ≥ 81` no longer ships — every «медиа и речь» job died with
  `No module named 'pkg_resources'`. `4.6.3` uses `importlib.resources.files` instead. Patch
  release, still `faster-whisper 1.2.0`-compatible.
- `[tts]` extra pinned `torch>=2.2,<3` → `torch==2.14.0` (CPU `win_amd64`, resolved on the target
  machine). Silero `v4_ru` narration verified end to end (48 kHz WAV, voice `eugene`).
- `MODEL_SETUP.md` updated.

## 2026-09-03 - Delete seasons, episodes and queue jobs from the panel

The Сезоны, Серии and Очередь lists were append-only. Added explicit deletion so a wrong import
or a dead job can be cleared without editing SQLite by hand.

- `app/application/deletion.py` — `delete_episode` / `delete_season` collect every dependent row
  (candidates + subtitles/snapshots/review/exports, transcript segments + word timestamps, scenes,
  outline, media tracks, speaker identities, jobs + job stages) and the derived trees
  (`cache/episodes|previews|keyframes/<fingerprint>`, `output/<fingerprint>`), then remove the DB
  rows in FK-safe order. `delete_season` also runs `delete_story_arc` per arc, drops season-level
  publishing plans and collects character photo paths. `ResourceBusyError` (HTTP 409) blocks
  deletion while a queue job for the series is queued/running/paused. `purge_artifacts` unlinks the
  collected files only inside `output_dir` / `cache_dir` / `characters_dir`.
- `app/application/story_arcs.py::prune_episode_from_story_arcs` — drops StoryArc segments that
  point at a deleted episode and refreshes the affected plans (`_normalize_segment_order` +
  `refresh_story_arc_plan` + `_touch_arc`), so a removed series cannot leave dangling montage rows.
- `app/workers/queue.py::delete_job` — removes a job and its `job_stages`; `JobBusyError`
  (HTTP 409) refuses a running / cancel-requested job.
- API: `DELETE /api/episodes/{id}`, `DELETE /api/seasons/{id}`, `DELETE /api/jobs/{id}`, each
  returning `{"deleted": true}`. `docs/openapi.json` + `docs/API.md` regenerated.
- Frontend: red trash control on every season and episode row, «Удалить» on every non-running
  queue job; `window.confirm` first, then `refresh()` / `refreshActivity()`. Selection state is
  cleared when the open episode is deleted.
- Tests: `tests/test_deletion.py` (row cascade, busy guard, arc pruning, season cascade, purge
  stays inside managed roots) and three job-delete cases in `tests/test_queue_endpoint.py`.

Verification: `pytest` 170 passed; `npm run test` (10) + `npm run build` + `tsc --noEmit` clean;
`alembic` unchanged (no schema change); manual smoke — real `DELETE /api/jobs/8` on a failed job
in the running app removed it and its stages.

## 2026-09-02 - Neural StoryArc Narration (Silero)

Replaced the flat Windows SAPI narration with a pluggable TTS layer so the hero's voiceover can
sound alive. Chosen after review of the main computer's specs (Ryzen 9 3950X, 64 GB, GTX 1660
Super — CPU-strong, 6 GB VRAM): a CPU neural engine, not GPU cloning.

- `app/media/tts.py` — `TtsSynthesizer` protocol with `SileroSynthesizer` (Silero v4_ru, CPU,
  model cached per class), `WindowsSapiSynthesizer` (the old System.Speech path), `StubTtsSynthesizer`
  (silent WAV for tests). `build_synthesizer(settings)` picks by `tts_adapter`.
- `app/application/narration_voice.py` — `resolve_narration_voice()`: explicit `Character.narration_voice`
  → auto by gender (name endings + description hints) → configured narrator voice. Migration `0015`
  adds `characters.narration_voice`.
- `narration.py` refactored to synthesize each line through the injected synthesizer and record the
  chosen `voice_id` in `plan_json`; `story_arc_render.py` is unchanged (reads the WAV path).
- Config: `tts_adapter` (`silero` default | `windows-sapi` | `stub`), `tts_model_path`,
  `tts_sample_rate`, `tts_narrator_voice`; the first two are UI-editable via `RuntimeSettings`.
- `torch` is an opt-in extra (`pip install -e ".[tts]"`, `torch>=2.2,<3` — pin the resolved
  version after first install). Silero adapter raises a clear error when torch or the model is
  absent; `windows-sapi` and `stub` need nothing.
- API: `GET /api/tts/voices`, `PUT /api/characters/{id}/narration-voice`; `model-catalog` gains a
  `tts` entry (in-app download of `v4_ru.pt` ~60 MB from models.silero.ai, verified by torch.package
  load); `model-diagnostics` reports torch/model/voice; `scripts/install_tts_model.ps1`.
- Frontend: Settings → "Озвучка StoryArc" (engine + narrator voice); character card → "Голос
  озвучки" select (auto shows the guessed voice); SystemPanel shows the TTS row.

Verification: `ruff` + `mypy` (100 files) clean; `pytest` 158 passed / 0 skipped (with FFmpeg);
`npm run build` + `npm run test` (10) pass; `alembic` round-trip clean; manual smoke of
`/api/tts/voices`, `/api/model-diagnostics`, the settings section and model catalog in a browser.
The Silero model itself was NOT downloaded on this laptop (dev machine) — install it on the main
computer with the extra + `scripts/install_tts_model.ps1`.

## 2026-09-02 - Workflow Feature Batch (health, history, batch ops, keyframes, models, docs)

Implemented the outstanding feature/gap list from the project review, in eight commits:

1. **Health / version / logs + path-safety.** `resolve_within()` (`app/domain/paths.py`) guards
   every generated-file endpoint (exports, story-arc exports, character photos) so a stale or
   hand-edited DB row cannot stream an arbitrary file; helper lives in `app/api/media_files.py`.
   `/api/health` now returns version, git commit, per-process `boot_id`, token fingerprint, uptime,
   db revision and queue state; new `/api/version` and `/api/logs` (rotating-log tail with
   level/text filters, `app/application/log_reader.py`). New `api_client` pytest fixture runs the
   app on an isolated in-memory schema.
2. **Adapter failure handling.** `LlamaCppHttpAnalyzer` retries a chunk once with a stricter prompt
   on invalid JSON. `LocalFaceRecognizer` and the cover picker no longer crash on OpenCV 5 headless
   (which drops `cv2.CascadeClassifier`); without YuNet/SFace the recognizer degrades to voice-only
   and `model-diagnostics` says so. Tests in `tests/test_adapter_failures.py`.
3. **End-to-end pipeline smoke** (`tests/test_e2e_pipeline.py`): generates a tiny MP4 and walks
   import -> probe -> stage2 (stub ASR/scene) -> stage3 (stub LLM) -> review -> render, verified
   with ffprobe. CI now installs ffmpeg so this and `test_media_smoke.py` actually run, plus a
   migration `downgrade base` / `upgrade head` round-trip.
4. **Candidate edit history** (migration `0014`). Every boundary/crop/subtitle change snapshots the
   previous state (pruned to 25). `GET /api/candidates/{id}/history`,
   `POST /api/candidates/{id}/history/{snapshot_id}/restore` (restore is itself snapshotted).
5. **Batch candidate operations.** `POST /api/episodes/{id}/candidates/batch-review` and
   `POST /api/candidates/batch-render-job` with per-candidate skip reasons.
6. **Keyframe strip.** `GET /api/candidates/{id}/keyframes[?count=]` extracts evenly-spaced JPEGs
   in one ffmpeg pass, cached by candidate id + edit revision; `/keyframes/{index}` serves one.
7. **Model install assistant + import progress + Windows diagnostics.** `GET /api/model-catalog`
   lists ASR/LLM/face models with size, target dir, install state and the exact command;
   `POST /api/model-catalog/{key}/install` downloads the small face models in-app behind a
   `confirm` flag with SHA-256 verification. `import_season` takes a progress callback, survives a
   file locked by antivirus/Explorer, and reports scanned count + per-file errors. `system-check`
   adds advisory node / llama-server / virtualenv / Windows long-path checks.
8. **API docs + bootstrap.** `scripts/dump_openapi.py` writes `docs/openapi.json` + `docs/API.md`
   from the live app (a test fails on drift). `scripts/bootstrap.ps1` checks prerequisites with
   actionable messages then sets up the environment; `Start SerialCuts.cmd` runs it on first launch.

Frontend: `BackendStatusBanner` (reload prompt on `boot_id` change / offline), `LogViewerPanel`,
`ModelCatalogPanel`, `KeyframeStrip`, `CandidateHistory`, `BatchActionBar` + per-card checkboxes,
richer import message. Wired into `AppView` as self-contained panels to avoid growing the
controller.

Verification: `ruff check .`, `mypy app` (98 files) clean; `pytest` 144 passed / 0 skipped with
ffmpeg on PATH; `npm run build` + `npm run test` (10) pass; `alembic upgrade head` /
`downgrade base` round-trip clean; manual smoke of `/api/health`, `/api/model-catalog`,
`/api/logs` and the new panels in a browser.

Environment note: the local `.venv` on this machine is still Python 3.10.4 and was missing
`numpy`, `opencv-python-headless`, `ruff`, `mypy`, `uvicorn`; installed them ad hoc to run checks.
Recreate the venv with Python 3.11 (`scripts/bootstrap.ps1`) for a clean state.

## 2026-09-01 - Backend CI Database Preparation

Follow-up after the first GitHub Actions run for the prompt work:

- GitHub backend CI passed install, `ruff` and `mypy`, then failed during `pytest` collection because
  `app.main` requires an Alembic-migrated database and the CI runner had no SQLite database yet.
- Updated `.github/workflows/ci.yml` so the backend job uses a dedicated `data/ci.db` database and
  runs `python -m alembic upgrade head` before `python -m pytest`.

Verification: reproduced the CI-style database setup locally with a temporary SQLite URL, then ran
`python -m alembic upgrade head`, `python -m ruff check .`, `python -m mypy app` and
`python -m pytest --basetemp data\pytest-tmp-ci3` (`107 passed`, `3 skipped`).

## 2026-09-01 - Dependency Registry Verification

Completed prompt point 6:

- Checked all pinned Python dependencies and new dev tools against PyPI JSON. Every pinned version
  in `pyproject.toml` exists. Notable latest registry versions at verification time included
  `pydantic 2.13.5`, `pydantic-settings 2.15.0`, `python-dotenv 1.2.3`,
  `faster-whisper 1.2.1`, `ctranslate2 4.8.2`, `python-telegram-bot 22.8`,
  `pytest 9.1.1`, `pytest-cov 7.1.0`, `ruff 0.16.5` and `mypy 2.3.1`, but no required
  pin was missing.
- Checked frontend pins against npm registry. Every pinned version in `frontend/package.json`
  exists; newer compatible registry versions were available for `@vitejs/plugin-react`,
  `lucide-react` and `vite`, but no missing pin required a change.
- Verified clean backend installation in a temporary venv created with Codex bundled Python 3.12.13:
  `python -m pip install -e ".[dev]"` succeeded with the existing pins.
- Confirmed the old local `.venv` uses Python 3.10.4; it cannot install `numpy==2.4.6` because
  the project requires Python 3.11+ and those wheels are not available for Python 3.10.
- Fixed the missing `VoiceEmbedding` import found while enabling CI checks.
- Tightened the initial CI baseline enough for automated runs to pass now: `ruff` keeps critical
  checks active while import-cleanup warnings from the mechanical router split are deferred, and
  `mypy` starts with a documented relaxed profile for existing SQLAlchemy/media typing debt.

Verification: PyPI/npm registry checks succeeded. Clean venv install succeeded. With the clean venv,
`python -m ruff check .` passed, `python -m mypy app` passed, Alembic upgraded a temporary SQLite DB
to head, `python -c "import app.main"` passed, and `python -m pytest --basetemp data\pytest-tmp`
passed (`107 passed`, `3 skipped`, one upstream Starlette deprecation warning). Frontend `npm ci`
passed with `0 vulnerabilities`, then `npm run build` and `npm run test` passed (`3 test files`,
`10 tests`).

## 2026-09-01 - Typecheck And CI Setup

Completed prompt point 5 configuration:

- Added backend dev tools `ruff` and `mypy` to `pyproject.toml`.
- Added a starter `[tool.mypy]` profile for Python 3.11 with unused-ignore warnings, relaxed
  untyped defs for the first pass and missing import ignores for optional media/AI packages.
- Added `.github/workflows/ci.yml` with separate backend and frontend jobs. Backend installs
  `.[dev]`, runs `ruff`, `mypy app` and `pytest`; frontend runs `npm ci`, `npm run build`
  and `npm run test`.
- Confirmed `frontend/tsconfig.json` already has `strict: true`; CI uses the existing `tsc -b`
  from `npm run build`.
- Documented CI scope in `README.md` and `ARCHITECTURE.md`, including that real models,
  GPU/NVENC and Windows-only launcher scripts are intentionally outside Linux CI.

Verification: configuration was added and documented. Local `ruff`/`mypy` execution is deferred
to the dependency-version pass because the current prompt explicitly marks several pinned
versions as suspicious and the local venv does not yet include these new dev tools.

## 2026-09-01 - Frontend App Split

Completed prompt point 4:

- Moved the React entry point to a tiny `frontend/src/main.tsx` and moved the application
  container to `frontend/src/App.tsx`.
- Added `frontend/src/hooks/useSerialCutsController.ts` for the UI state/API orchestration that
  previously lived directly in `main.tsx`.
- Added `frontend/src/hooks/useCandidates.ts` for candidate filtering, sorting, selected edits and
  moment type derivation.
- Added `frontend/src/components/AppView.tsx` as the presentation layer fed by the controller hook.
- Added `frontend/src/hooks/useCandidates.test.ts` covering filtering, score threshold, search,
  problem filtering, boundary sorting and moment type extraction.

Verification: `npm run build` passed (`tsc -b` + Vite production build). `npm run test` passed
outside the sandbox after the known local `spawn EPERM` issue (`3 test files`, `10 tests`).

## 2026-09-01 - API Router Split

Completed prompt point 3:

- Split the former 1486-line `app/api/routes.py` into domain routers:
  `settings_and_diagnostics_routes.py`, `seasons_routes.py`, `episodes_routes.py`,
  `candidates_routes.py`, `story_arcs_routes.py`, `characters_routes.py`,
  `publishing_routes.py` and `exports_routes.py`.
- Moved shared HTTP mappers and guard helpers into `app/api/_shared.py`.
- Added `app/api/router.py` with the domain router registry and kept `app/api/routes.py`
  as a compatibility shim for older imports.
- Updated `app/main.py` to include the domain routers directly, plus the existing queue and
  search routers.
- Added `tests/test_api_router_structure.py` to check representative API paths and enforce
  route module size, with `schemas.py` intentionally exempted by the prompt scope.

Verification: `.\.venv\Scripts\python.exe -m pytest tests\test_api_router_structure.py
tests\test_api_errors.py tests\test_logging_config.py tests\test_queue.py` passed (`11 passed`,
one upstream Starlette deprecation warning). `.\.venv\Scripts\python.exe -m compileall -q app\api`
passed. `git diff --check` passed with line-ending warnings only.

## 2026-09-01 - Runtime Logging Pass

Completed prompt point 2:

- Added `app/infrastructure/logging_config.py` with centralized console logging and rotating
  `data/logs/serialcuts.log` output.
- Added `SERIALCUTS_LOG_LEVEL` with validation in settings and `.env.example`.
- Wired logging into FastAPI startup before database migration checks.
- Added lifecycle and failure logs around the background queue, job stages, FFmpeg/ffprobe,
  faster-whisper, local llama.cpp requests, render fallback and cover generation.
- Kept existing CLI `print(...)` output in benchmark and system-check commands only.
- Added `tests/test_logging_config.py` for UTF-8 file output and idempotent handler setup.

Verification: `.\.venv\Scripts\python.exe -m pytest tests\test_logging_config.py
tests\test_api_errors.py tests\test_queue.py` passed (`9 passed`, one upstream Starlette
deprecation warning). `git diff --check` passed with line-ending warnings only.

## 2026-09-01 - API Error Boundary Pass

Completed prompt point 1:

- Added `app/api/errors.py` with shared application exceptions and FastAPI exception handlers for
  domain errors, `ValueError`, `ProcessingBusyError`, database integrity conflicts and unexpected
  runtime failures.
- Wired the handlers into `app/main.py`; unexpected API exceptions now return a generic 500 response
  and log the internal exception instead of exposing details as a 400.
- Replaced broad `except Exception` blocks in `app/api/routes.py` and `app/api/queue_routes.py` with
  narrower expected-error catches. `rg -n "except Exception" app/api --glob "*.py"` now returns no
  API matches.
- Added `tests/test_api_errors.py` for readable 400 domain errors and generic logged 500 responses.

Verification: `.\.venv\Scripts\python.exe -m pytest tests\test_api_errors.py
tests\test_remaining_audit_hardening.py tests\test_queue.py` passed (`13 passed`, one upstream
Starlette deprecation warning).

## 2026-09-01 - Queue-First Runtime Hardening

Implemented the selected project weaknesses 1, 3, 4, 5, 6, 7 and 8 without changing the launcher:

- Added a process-local `X-SerialCuts-Token` requirement for unsafe local HTTP methods while keeping
  GET/HEAD/OPTIONS and testclient flows lightweight. The React API helper fetches the token from the
  same-origin backend and attaches it automatically.
- Episode enqueue now accepts `resume_from_stage`, `auto`, threshold, max clip and NVENC payload
  fields, so the UI can queue media-only, candidate-only and auto-export work instead of running
  long media/LLM/render steps inside a blocking request.
- Stage 2 speaker labeling is lazy and optional. If speaker clustering fails, the media pipeline
  stores a `serialcuts_warnings` entry in `episode.probe_json` and returns the warning instead of
  silently losing character-quality context.
- Project diagnostics now detect the current Alembic head dynamically and surface episodes with
  analysis warnings.
- StoryArc narration has explicit `first_person`, `narrator` and `none` modes. First-person mode
  falls back to narrator when no target character exists, and render fingerprints/metadata include
  the effective narration mode.
- Added a generated-media StoryArc smoke test that builds two tiny local MP4 sources, renders a
  multi-source StoryArc, and verifies the resulting MP4 streams with ffprobe.
- Moved the ready-export gallery into `frontend/src/components/ExportsPanel.tsx` and expanded the
  StoryArc workflow block so narration controls are easier to maintain.

Verification: focused backend hardening tests passed (`26 passed`, `3 skipped` where FFmpeg/ffprobe
are unavailable in this environment); focused StoryArc/security/queue/media tests passed (`19 passed`,
`3 skipped`); frontend production build passed; frontend Vitest passed (`7 tests`) when run outside
the sandbox after an initial sandbox `spawn EPERM`; quality benchmark averaged `85/100`. The local
live DB in this checkout is still on an older revision, so `tests/test_api_stage2.py` was not used
for this verification to avoid migrating local laptop data.

## 2026-09-01 - Remaining Full-Audit Hardening

Completed audit findings 1-4, 6, 12 and 13:

- Cache cleanup now requires a validated `.serialcuts-cache` marker, rejects paths that could contain
  the project, an imported episode or output, and is blocked while resumable jobs exist.
- Proxy files include the selected Russian AAC track and use a v2 filename so silent legacy proxies
  are not reused. Candidate and StoryArc render commands explicitly map each episode's selected
  audio stream.
- SQLite jobs are atomically claimed with a process identity, renewable lease and heartbeat. Only one
  heavy job can own the global lease across application processes; expired leases are recovered, and
  failed SQLAlchemy sessions roll back before stage/job failure is recorded in a fresh transaction.
- Candidate and StoryArc exports are immutable versions with unique paths and complete render
  fingerprints (source, stream, ranges, crop, subtitles/style, preset, loudnorm, transitions and
  narration content). Publishing plans therefore keep pointing to the exact MP4 they were built for.
- The HTTP app is loopback-only at settings, launcher and ASGI boundaries. Startup no longer calls
  `create_all`; it requires the current Alembic revision and provides an upgrade command otherwise.
- Stage 3 and StoryArc deletion clean only explicit derived files contained by cache/output roots.
- Updated advisory-affected tooling to python-dotenv 1.2.2, pytest 9.0.3 and setuptools 84.0.0.
- Added Alembic revision `0013_remaining_audit_hardening`; upgraded the live database to head.

Verification: backend suite passed (`101 tests`, one upstream Starlette warning); frontend Vitest
passed (`6 tests`); frontend production build passed; `pip check`, Alembic current and every system
check passed. Original media was not modified and no media/transcript data left the computer.

This file is the durable project memory for Codex sessions on the laptop and desktop. Update it after meaningful changes so a new task can continue without needing the full chat history.

## 2026-09-01 - Audit Weaknesses 5, 7-11 And 14

Hardened the selected findings from the full-project audit:

- Enforced privacy at configuration boundaries: llama.cpp URLs must resolve to `localhost` or a
  loopback IP and cannot contain credentials.
- Rebuilt StoryArc narration as individually synthesized lines placed on the montage timeline,
  rejected narration that cannot fit without excessive speed-up, and used sidechain compression so
  source audio is ducked only while narration speaks.
- StoryArc crossfades now preserve the chosen render bitrate/audio preset and NVENC preference, with
  the existing CPU fallback. Final duration accounts for transition overlap.
- Added persisted job messages and start/finish timestamps, real-history ETA per job kind, granular
  Whisper/Qwen/scene/render progress, and responsive cancellation through FFmpeg and model loops.
- Escaped ASS cue text and font fields while preserving generated line breaks/bold speaker labels.
- Persisted StoryArc build constraints so rebuilds retain the original segment/duration limits.
- Added SQLite FTS5 indexes with update/delete triggers and bounded semantic reranking for season
  search. Split queue/search API routers and queue/system React panels out of monolithic files.
- Added Alembic revision `0012_runtime_quality_hardening`; upgraded the live database from `0011`
  to head after creating `data/serialcuts.db.bak-0011-20260901`.

Verification: backend suite passed (`95 tests`, one upstream deprecation warning), including a real
FFmpeg narration-timeline/ducking smoke; frontend Vitest
passed (`6 tests`); frontend production build passed; migration reached
`0012_runtime_quality_hardening`; OpenAPI contains the split queue/search routes. Original media was
not modified and no external service was contacted.

## 2026-09-01 - Reliability And Narrative Quality Pass

Completed the full improvement list from the repository review:

- Candidate and StoryArc edits now carry revisions. Boundary/crop changes invalidate old renders,
  subtitles and linked plans instead of silently reusing an obsolete MP4. Manual StoryArc segment
  edits survive rebuilds, duplicates are ignored and ranges snap to complete transcript lines.
- StoryArc selection now combines deterministic ranking with local semantic matching and optional
  Qwen ordering. Regenerating episode candidates preserves linked StoryArc ranges as snapshots.
- StoryArc render now uses real video/audio crossfades, exact per-segment subtitles, optional local
  narration mixed over ducked source audio, atomic output replacement, per-segment progress and
  FFmpeg cancellation from the queue.
- Subtitle grouping splits on speakers, punctuation, pauses, length and reading speed. Confirmed
  character names flow into generated subtitles. Cover selection samples several frames and scores
  sharpness, exposure and faces.
- Auto-follow samples adaptively, holds a nearby face through short misses and gates lip motion with
  local audio energy. Voice profiles retain diverse v2 prototypes while remaining compatible with
  v1 profiles.
- Added local semantic season search, local-Qwen script/narration generation with deterministic
  fallback, platform limits/status validation and a privacy-preserving local `publishing.json`
  package. No external upload was added.
- Diagnostics now check Alembic revision, FFmpeg/ffprobe, free disk space, missing/stale exports and
  failed jobs. SQLite enables foreign keys in addition to WAL and a 30-second busy timeout.
- Split frontend API/types/utilities/settings components out of `main.tsx`, exposed narration,
  transition, stale-render, publishing-package and auto-crop confidence states, and added Vitest
  coverage.
- Added Alembic revisions `0010_render_consistency` and `0011_job_stage_consistency`, generated-media FFmpeg/ffprobe smoke coverage,
  two more narrative quality fixtures and focused regression tests.

Verification: live database upgraded from `0006` through `0011_job_stage_consistency`; backend suite
passed (`85 tests`); frontend production
build passed; Vitest passed (`6 tests`); generated H.264/AAC vertical media smoke passed; quality
benchmark averaged `85/100`; and all system checks passed with Python 3.11.9, FFmpeg 9.0.1,
ffprobe, GTX 1660 SUPER and 136 GB free. Existing diagnostics still report one failed historical job,
one unavailable source path and two missing legacy export files; no original media was modified.

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
- Operability: `/api/health` (version, boot_id, queue), `/api/version`, `/api/logs` tail + in-UI log
  viewer, `/api/model-catalog` + in-app face/Silero model install, candidate edit history/undo,
  batch candidate review/render, keyframe-thumbnail crop strip, generated `docs/API.md`,
  path-traversal guard + Host-header allowlist on the API, `scripts/bootstrap.ps1`, season/episode/
  job deletion.
- Neural StoryArc narration (Silero v4_ru on CPU, `.[tts]` extra) with per-character voice or auto
  by gender; Windows SAPI and stub adapters remain.
- Face tracking (auto-follow crop) needs local YuNet/SFace weights; without them auto-crop returns
  a clear 422 instead of silently centering. Degraded features (no Qwen, no ru-RU SAPI voice,
  loudnorm fallback, speaker-clustering failure) now surface a visible warning.

## Verification Snapshot

Last known checks from this project state (2026-09-04):

- `.\.venv\Scripts\python.exe -m pytest`: 178 passed, 0 skipped (with FFmpeg on PATH; needs
  `numpy`, `opencv-python-headless`, `scenedetect-headless` from the main dependency set).
- `python -m ruff check .` and `python -m mypy app` (102 files): clean.
- `npm run lint` / `npm run typecheck` / `npm run build` / `npm run test` (10): clean.
- `alembic upgrade head` then `downgrade base` then `upgrade head`: clean (schema at `0015`).
- 50/50 end-to-end API checks green (import → render → StoryArc → deletion, real FFmpeg + YuNet).
- `.\scripts\check_system.ps1` / `.\scripts\bootstrap.ps1`: work; target machines need Python 3.11+
  and FFmpeg/ffprobe in `PATH`.

## Key Decisions

- Original media files are read-only and must never be modified, deleted, or uploaded.
- No external AI APIs for media, frames, audio, subtitles, transcripts, or analysis.
- No Docker in MVP.
- Heavy local adapters load lazily and have stubs for tests.
- FFmpeg commands are built as argument arrays, without shell execution.
- Derived outputs belong in cache/output directories, not next to original episodes unless explicitly configured.
- App settings may override product behavior but must not write secrets or mutate `.env`.

## Near-Term Next Steps

Done in the 2026-09-02..04 work: model installation assistant, keyframe-thumbnail crop UX,
import progress + Windows diagnostics, end-to-end smoke fixture, candidate edit history/undo,
batch candidate operations, in-UI log viewer, generated API docs, bootstrap script, Silero
neural narration, season/episode/job deletion, loopback Host allowlist, frontend ESLint,
face-tracking + silent-degradation hardening.

Still open:

- Number-to-words normalization for Russian digits before TTS (Silero reads "2024" poorly).
- Recreate the local `.venv` on Python 3.11 and re-pin dev extras that live only in `dependencies`.
- Split `useSerialCutsController.ts` (750+ lines) into per-domain hooks.
- Tighten the ruff/mypy ignore lists (`from _shared import *`, 8 disabled mypy codes).
- Persistent background queue loop option, while keeping `run-next` for testability.
- Progress streaming (SSE) for long model downloads and season imports.
- VLM keyframe analysis for top candidates (declared in ARCHITECTURE, not built).

## Useful Commands

```powershell
git pull --ff-only
.\scripts\bootstrap.ps1            # checks Python 3.11 / FFmpeg / Node, then venv + install + migrate + frontend
.\.venv\Scripts\python.exe -m pip install -e ".[tts]"          # optional: Silero narration
.\scripts\install_tts_model.ps1                                # optional: Silero v4_ru model
.\scripts\install_identity_models.ps1                          # YuNet/SFace for face tracking
.\scripts\check_system.ps1
.\scripts\run.ps1
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\dump_openapi.py             # after changing any route
Push-Location frontend
npm run lint; npm run typecheck; npm run build; npm run test
Pop-Location
```

## Remote

`git@github.com:Ayan-18/serial-cut.git`

