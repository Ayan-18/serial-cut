# Архитектура SerialCuts

## Принципы

- Один Python-проект для MVP: FastAPI, SQLite, локальный worker.
- Исходные файлы всегда read-only.
- Внешние процессы запускаются массивом аргументов, без `shell=True`.
- Тяжёлые AI-адаптеры изолируются за интерфейсами; первый этап добавляет точки подключения, но не грузит модели.
- Каждый этап сохраняет состояние в SQLite и может продолжиться после перезапуска.
- FastAPI принимает клиентов только с loopback; LAN-bind блокируется конфигом, launcher и middleware.
- Схему создаёт только Alembic: приложение проверяет текущую revision и не вызывает `create_all()` в production-startup.

## Модули

- `app/api` - HTTP API для панели. Доменные routers разделены по файлам:
  `settings_and_diagnostics_routes.py`, `seasons_routes.py`, `episodes_routes.py`,
  `candidates_routes.py`, `candidate_history_routes.py`, `candidate_batch_routes.py`,
  `candidate_media_routes.py`, `story_arcs_routes.py`, `characters_routes.py`,
  `publishing_routes.py`, `exports_routes.py`, плюс отдельные `queue_routes.py`,
  `search_routes.py` и `events_routes.py` (`GET /api/events` — SSE-поток очереди и
  задач, замена постоянного опроса `GET /api/jobs`). Общие HTTP helper-функции лежат в
  `app/api/_shared.py`, отдача генерированных файлов проходит через
  `app/api/media_files.py` (`resolve_within` не выпускает путь за пределы output/cache),
  а `app/api/routes.py` оставлен тонким
  compatibility shim. Каждый route-модуль ≤ 300 строк (проверяется тестом).
- `app/application` - сценарии приложения: импорт сезона, system-check.
- `app/domain` - статусы, константы, работа с путями.
- `app/infrastructure` - конфиг, БД, процессы, fingerprint.
- `app/media` - FFmpeg/ffprobe и будущие media-операции.
- `app/models` - SQLAlchemy-модели.
- `app/workers` - persistent queue и восстановление задач.
- `frontend` - React + TypeScript панель.
- `migrations` - Alembic.
- `scripts` - Windows PowerShell-команды установки, запуска и диагностики.
- `.github/workflows/ci.yml` - GitHub Actions CI: backend lint/typecheck/tests и frontend
  build/tests. Реальные локальные модели, GPU/NVENC и Windows-only launcher не выполняются в CI.

## Этапы конвейера

1. `discovered`
2. `probed`
3. `proxied`
4. `transcribed`
5. `scenes_detected`
6. `outlined`
7. `candidates_generated`
8. `candidates_validated`
9. `awaiting_review` или `auto_approved`
10. `rendered`

В первом этапе реализованы `discovered`, базовый `probed`, очередь и восстановление running-job в queued.

Во втором этапе реализованы `proxied`, `transcribed` и `scenes_detected`:

- `FFmpegMediaPreparer` выбирает русскую аудиодорожку и русские субтитры, если они есть.
- Audio artifact: mono WAV 16 kHz для ASR.
- Proxy artifact: уменьшенный H.264 MP4 без аудио для веб-просмотра и scene detection.
- `FasterWhisperTranscriber` загружается лениво и имеет fallback compute type.
- `PySceneDetectAdapter` загружается лениво и использует AdaptiveDetector.
- `StubTranscriber`, `StubSceneDetector` и test media preparer позволяют гонять smoke pipeline без GPU/FFmpeg.

## Следующие адаптеры

- ASR: `faster-whisper`, русский язык, word timestamps, VAD, compute type `int8_float16` с fallback на `int8`.
- LLM: локальный `llama.cpp` HTTP на loopback-адресе, строгий JSON через Pydantic; конфиг отклоняет внешние LLM URL.
- VLM: опционально, только ключевые кадры верхних кандидатов (точка подключения не построена).
- Render: FFmpeg с NVENC при успешной диагностике, fallback `libx264`.

## Идемпотентность Stage 2

Audio/proxy не пересоздаются, если уже существуют в cache для fingerprint серии. Proxy v2 содержит выбранную русскую AAC-дорожку; финальный render явно передаёт сохранённый stream index FFmpeg. Transcript и scenes заменяются детерминированно: старые производные записи удаляются, новые сохраняются в рамках текущей транзакции. Повторный запуск Stage 2 не создаёт дубликаты сегментов или сцен.

## Stage 3-5

- `stage3.py` строит outline, вызывает analyzer и сохраняет кандидатов.
- `analysis/schemas.py` задаёт строгий JSON-контракт LLM.
- `analysis/validation.py` корректирует границы по словам/сценам и удаляет сильно пересекающиеся кандидаты.
- `review.py` сохраняет approve/reject и не плодит одинаковые решения.
- `subtitles.py` форматирует русские SRT/ASS для мобильного просмотра.
- `rendering.py` строит FFmpeg-композицию 1080x1920: резкое окно 1080x1280 по центру и
  затемнённый размытый фон. `center-crop` и `auto-follow` различаются только горизонтальным
  положением окна в исходнике; legacy `blurred-background` — alias для центра. Zoom ограничен
  окном, та же геометрия используется в `FramedPreview` и StoryArc. Версия компоновки и доля
  высоты входят в общий render fingerprint, поэтому старый MP4 не подменяет новый результат.
- `stage4.py` создаёт MP4, subtitle artifact, cover и JSON metadata, затем сохраняет `Export`.
- `bot/callbacks.py` ставит одобрение/рендер выбранного кандидата в общую очередь (`enqueue`)
  и хранит idempotency key в `AppSetting`, поэтому повторное нажатие кнопки не создаёт дубль.
- `bot/telegram.py` запускает long polling без webhook/VPS: команды навигации по сериям и
  кандидатам, inline-кнопки approve/reject/render, а `bot/notifications.py` из воркера шлёт
  владельцу из whitelist уведомления о завершении задач.

## Product Workflow

- `application/settings.py` хранит UI-настройки в `AppSetting`, а `effective_settings` накладывает их поверх `.env`, не трогая секреты и системные пути FFmpeg.
- `workers/runner.py` выполняет analyze/render job, а `workers/background.py` постоянно забирает queued-задачи. Claim выполняется атомарным SQLite UPDATE; worker-id, lease и heartbeat не позволяют двум процессам одновременно выполнять тяжёлые задания. Восстанавливаются только задачи с истёкшим lease.
- `application/auto.py` выбирает кандидаты по порогу и лимиту, сохраняет approve и запускает render;
  `application/auto_crop.py` строит траекторию crop по лицам для одного кандидата.
- `application/candidate_editor.py` хранит ручные субтитры отдельно от распознавания, поэтому исходный transcript остаётся неизменным.
- `media/face_tracking.py` строит траекторию crop из трёх проходов: (1) плотная выборка кадров с
  доп. пробами сразу после старта каждой реплики; для каждого кадра — центры лиц, стабильный
  `track_id` (nearest-centroid), lip-motion по каждому лицу, активная реплика диаризации; (2) по
  всему клипу голосованием определяется экранная позиция каждого `speaker_label`; (3) траектория
  режется на «владельцев» (персонаж → метка диаризации → lip-winner → удержание → крупнейшее лицо),
  короткие реплики (< `_MIN_DWELL_SECONDS`) вклеиваются в соседний план. Каждый план — **одна
  фиксированная рамка** (без панорамирования и дрейфа), на смене говорящего — жёсткий рез (пара
  keyframe в `CUT_GAP_SECONDS`). План кадрируется на лицо только если ≥ `_CONFIDENT_RUN_FRACTION`
  кадров плана дали явного говорящего; иначе (толпа, спикер вне кадра, общий план) — просто центр.
  `_center_offset` с `_CENTERING_GAIN` ставит лицо из левой/правой трети в середину 9:16-окна.
  `media/speakers.py` выполняет первичную кластеризацию реплик.
- `application/characters.py` хранит локальную библиотеку персонажей, привязки голосовых кластеров и обновляет подтверждённые voiceprint-профили без открытой транзакции во время media-анализа.
- `media/character_recognition.py` использует локальные YuNet + SFace, несколько референсных фотографий и lip-motion; OpenCV 5 не содержит Haar-каскада, поэтому без ONNX-весов распознавание по лицу отключается и работает только идентификация по голосу.
- `media/voice_identity.py` строит 76-мерный log-mel/cepstral voiceprint, объединяет подтверждённые образцы и консервативно переносит имя между сериями.
- Централизованные логи настраиваются в `infrastructure/logging_config.py`: console + rotating
  `data/logs/serialcuts.log`, уровень берётся из `SERIALCUTS_LOG_LEVEL`.
- Voice profile v2 хранит до 12 разнообразных локальных прототипов голоса, но продолжает читать v1.
- Story context хранится на уровне сезона/серии. Stage 3 передаёт его вместе с outline локальной Qwen и в режиме `story` сохраняет хронологический номер и драматургическую роль кандидата.
- Stage 4 превращает keyframes во временное FFmpeg crop-выражение. `media/rendering.py::smooth_crop_keyframes`
  ограничивает скорость панорамирования только для плавных переходов: пара keyframe ближе
  `_CUT_GAP_SECONDS` — это намеренный рез трекера и проходит без сглаживания.
- `analysis/quality.py` калибрует оценки по речи/сценам, проверяет границы фраз и удаляет почти одинаковые моменты из разных серий.
- `media/rendering.py` поддерживает crop offset/scale, render presets, NVENC detect, export без субтитров и двухпроходный loudnorm helper.
- Candidate/StoryArc revisions и полный render fingerprint связывают ручные правки и настройки с производными экспортами. Экспорты неизменяемы: каждый повторный render создаёт новую версию и путь, поэтому PublishingPlan сохраняет точную версию MP4.
- `application/story_arc_render.py` рендерит источники отдельно, затем выполняет `xfade` + `acrossfade` с выбранным preset/NVENC и смешивает разложенную по таймлайну TTS через sidechain ducking.
- `media/tts.py` — движки озвучки за протоколом `TtsSynthesizer`: `SileroSynthesizer` (нейросетевой русский голос v4_ru на CPU, модель кэшируется в классе), `WindowsSapiSynthesizer` (System.Speech), `StubTtsSynthesizer`; `build_synthesizer(settings)` выбирает по `tts_adapter`. `application/narration_voice.py` определяет голос: явный `Character.narration_voice` (миграция `0015`) → авто по полу из имени/описания → голос диктора. `narration.py` синтезирует построчно и раскладывает по таймлайну; `media/ru_numbers.py` перед синтезом разворачивает цифры в слова («2024» → «две тысячи двадцать четыре»).
- Длительные FFmpeg/Whisper/scene/LLM-этапы проверяют отмену и сообщают детальный прогресс; ETA берётся из реальных `started_at`/`finished_at`. Итоговые MP4, JSON, ASS, cover и narration artifacts заменяются атомарно.
- `analysis/text_similarity.py` даёт полностью локальный русский semantic fallback; FTS5 ограничивает пул кандидатов/реплик для больших сезонов, а при доступной Qwen планировщик дополнительно валидирует предложенный моделью порядок частей.
- `application/publishing.py` валидирует лимиты/статусы платформ и создаёт локальный manifest; внешняя публикация не входит в privacy-first MVP.
- `application/project_diagnostics.py` проверяет миграцию, инструменты, свободное место, потерянные и устаревшие производные файлы.
- UI показывает вертикальный preview, subtitle/crop editor, фильтры, живую очередь, историю экспортов, диагностику моделей и подтверждённую очистку только cache. Очередь и задачи обновляются подпиской `EventSource` на `GET /api/events`; при обрыве потока фронтенд временно откатывается на короткий опрос.
- `scripts/run_local.ps1` работает как супервизор: поднимает `llama-server`, применяет миграции, запускает uvicorn и в цикле проверяет `/health` локальной Qwen, перезапуская её при зависании; `finally` гасит оба процесса.
- `application/runtime_info.py` собирает `/api/health` (версия, git-commit, `boot_id` процесса,
  отпечаток токена, аптайм, ревизия БД, очередь); `application/log_reader.py` парсит хвост
  ротируемого журнала (`current_log_path()` из `logging_config`) с фильтрами по уровню/тексту.
- `application/edit_history.py` + модель `CandidateEditSnapshot` (миграция `0014`) хранят снимки
  геометрии и субтитров кандидата перед каждой правкой и откатывают к выбранному снимку;
  `_apply_candidate_edits` и `save_candidate_subtitles` вызывают `record_candidate_snapshot`.
- `application/batch_ops.py` применяет approve/reject и постановку рендера к списку кандидатов,
  возвращая причину пропуска для каждого; `application/candidate_keyframes.py` +
  `media/thumbnails.py` собирают полосу миниатюр одним проходом FFmpeg с кэшем по
  `candidate.edit_revision`.
- `application/model_install.py` описывает каталог моделей (размер, папка, статус, команда) и
  качает небольшие модели лиц по подтверждению с проверкой SHA-256; `scripts/download_identity_models.py`
  использует его же.
- `importer.py` принимает progress callback, пропускает заблокированные файлы в `errors` и не
  прерывает импорт; `system_check.py` добавляет необязательные проверки (Node, `llama-server`,
  запуск вне `.venv`, длинные пути Windows) через набор `OPTIONAL_CHECKS`.
- `scripts/dump_openapi.py` генерирует `docs/openapi.json` и `docs/API.md` из живого приложения;
  тест падает при расхождении. `scripts/bootstrap.ps1` — проверка окружения и установка.
- `application/deletion.py` удаляет серию или сезон целиком: собирает все зависимые строки
  (кандидаты и их субтитры/снимки/решения/экспорты, транскрипт и слова, сцены, outline, дорожки,
  привязки говорящих, задачи и их этапы) и производные каталоги по `fingerprint`, чистит StoryArc
  через `prune_episode_from_story_arcs`, затем удаляет файлы только в пределах
  `output_dir`/`cache_dir`/`characters_dir`. Активная задача в очереди (`ResourceBusyError` → 409)
  блокирует удаление. `workers/queue.py::delete_job` убирает задачу и её `job_stages`
  (`JobBusyError` → 409 для выполняющейся). Эндпоинты: `DELETE /api/episodes/{id}`,
  `DELETE /api/seasons/{id}`, `DELETE /api/jobs/{id}`.
