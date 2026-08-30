# Архитектура SerialCuts

## Принципы

- Один Python-проект для MVP: FastAPI, SQLite, локальный worker.
- Исходные файлы всегда read-only.
- Внешние процессы запускаются массивом аргументов, без `shell=True`.
- Тяжёлые AI-адаптеры изолируются за интерфейсами; первый этап добавляет точки подключения, но не грузит модели.
- Каждый этап сохраняет состояние в SQLite и может продолжиться после перезапуска.

## Модули

- `app/api` - HTTP API для панели.
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
- LLM: локальный `llama.cpp` HTTP на `127.0.0.1`, строгий JSON через Pydantic.
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
- `media/face_tracking.py` оценивает горизонтальное положение лиц локально; `media/speakers.py` эвристически группирует голоса без внешних сервисов.
- `analysis/quality.py` калибрует оценки по речи/сценам, проверяет границы фраз и удаляет почти одинаковые моменты из разных серий.
- `media/rendering.py` поддерживает crop offset/scale, render presets, NVENC detect, export без субтитров и двухпроходный loudnorm helper.
- UI показывает вертикальный preview, subtitle/crop editor, фильтры, живую очередь, историю экспортов, диагностику моделей и подтверждённую очистку только cache.
