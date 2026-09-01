# Архитектура SerialCuts

## Принципы

- Один Python-проект для MVP: FastAPI, SQLite, локальный worker.
- Исходные файлы всегда read-only.
- Внешние процессы запускаются массивом аргументов, без `shell=True`.
- Тяжёлые AI-адаптеры изолируются за интерфейсами; первый этап добавляет точки подключения, но не грузит модели.
- Каждый этап сохраняет состояние в SQLite и может продолжиться после перезапуска.

## Модули

- `app/api` - HTTP API для панели; очередь и поиск вынесены в отдельные routers.
- `app/application` - сценарии приложения: импорт сезона, system-check.
- `app/domain` - статусы, константы, работа с путями.
- `app/infrastructure` - конфиг, БД, процессы, fingerprint.
- `app/media` - FFmpeg/ffprobe и будущие media-операции.
- `app/models` - SQLAlchemy-модели.
- `app/workers` - persistent queue и восстановление задач.
- `frontend` - React + TypeScript панель.
- `migrations` - Alembic.
- `scripts` - Windows PowerShell-команды установки, запуска и диагностики.

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
- VLM: опционально, только ключевые кадры верхних кандидатов.
- Render: FFmpeg с NVENC при успешной диагностике, fallback `libx264`.

## Идемпотентность Stage 2

Audio/proxy не пересоздаются, если уже существуют в cache для fingerprint серии. Transcript и scenes заменяются детерминированно: старые производные записи удаляются, новые сохраняются в рамках текущей транзакции. Повторный запуск Stage 2 не создаёт дубликаты сегментов или сцен.

## Stage 3-5

- `stage3.py` строит outline, вызывает analyzer и сохраняет кандидатов.
- `analysis/schemas.py` задаёт строгий JSON-контракт LLM.
- `analysis/validation.py` корректирует границы по словам/сценам и удаляет сильно пересекающиеся кандидаты.
- `review.py` сохраняет approve/reject и не плодит одинаковые решения.
- `subtitles.py` форматирует русские SRT/ASS для мобильного просмотра.
- `rendering.py` строит 1080x1920 FFmpeg-команды для `center-crop`, `auto-follow` и `blurred-background`.
- `stage4.py` создаёт MP4, subtitle artifact, cover и JSON metadata, затем сохраняет `Export`.
- `bot/callbacks.py` хранит idempotency key в `AppSetting`.
- `bot/telegram.py` запускает long polling без webhook/VPS.

## Product Workflow

- `application/settings.py` хранит UI-настройки в `AppSetting`, а `effective_settings` накладывает их поверх `.env`, не трогая секреты и системные пути FFmpeg.
- `workers/runner.py` выполняет analyze/render job, а `workers/background.py` постоянно и последовательно забирает queued-задачи, восстанавливая работу после перезапуска.
- `application/auto.py` выбирает кандидаты по порогу и лимиту, сохраняет approve и запускает render.
- `application/candidate_editor.py` хранит ручные субтитры отдельно от распознавания, поэтому исходный transcript остаётся неизменным.
- `media/face_tracking.py` выбирает активного говорящего по подтверждённому SFace-совпадению или движению области рта и сохраняет траекторию crop; `media/speakers.py` выполняет первичную кластеризацию реплик.
- `application/characters.py` хранит локальную библиотеку персонажей, привязки голосовых кластеров и обновляет подтверждённые voiceprint-профили без открытой транзакции во время media-анализа.
- `media/character_recognition.py` использует локальные YuNet + SFace, несколько референсных фотографий и lip-motion; при отсутствии весов остаётся резервный Haar/DCT-режим.
- `media/voice_identity.py` строит 76-мерный log-mel/cepstral voiceprint, объединяет подтверждённые образцы и консервативно переносит имя между сериями.
- Voice profile v2 хранит до 12 разнообразных локальных прототипов голоса, но продолжает читать v1.
- Story context хранится на уровне сезона/серии. Stage 3 передаёт его вместе с outline локальной Qwen и в режиме `story` сохраняет хронологический номер и драматургическую роль кандидата.
- Face tracking приоритетно следует за подтверждённым активным персонажем, затем за ртом с максимальным движением; Stage 4 превращает сглаженные keyframes во временное FFmpeg crop-выражение.
- `analysis/quality.py` калибрует оценки по речи/сценам, проверяет границы фраз и удаляет почти одинаковые моменты из разных серий.
- `media/rendering.py` поддерживает crop offset/scale, render presets, NVENC detect, export без субтитров и двухпроходный loudnorm helper.
- Candidate/StoryArc revisions связывают ручные правки с производными экспортами; несовпавший render помечается `stale` и не переиспользуется.
- `application/story_arc_render.py` рендерит источники отдельно, затем выполняет `xfade` + `acrossfade` с выбранным preset/NVENC и смешивает разложенную по таймлайну TTS через sidechain ducking.
- Длительные FFmpeg/Whisper/scene/LLM-этапы проверяют отмену и сообщают детальный прогресс; ETA берётся из реальных `started_at`/`finished_at`. Итоговые MP4, JSON, ASS, cover и narration artifacts заменяются атомарно.
- `analysis/text_similarity.py` даёт полностью локальный русский semantic fallback; FTS5 ограничивает пул кандидатов/реплик для больших сезонов, а при доступной Qwen планировщик дополнительно валидирует предложенный моделью порядок частей.
- `application/publishing.py` валидирует лимиты/статусы платформ и создаёт локальный manifest; внешняя публикация не входит в privacy-first MVP.
- `application/project_diagnostics.py` проверяет миграцию, инструменты, свободное место, потерянные и устаревшие производные файлы.
- UI показывает вертикальный preview, subtitle/crop editor, фильтры, живую очередь, историю экспортов, диагностику моделей и подтверждённую очистку только cache.
