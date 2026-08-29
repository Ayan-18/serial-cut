# SerialCuts

SerialCuts - локальное Windows-приложение для поиска осмысленных фрагментов в сериях с русской озвучкой и подготовки вертикальных MP4 для YouTube Shorts / Instagram Reels. MVP не публикует ролики автоматически и не отправляет исходные видео, кадры, аудио или расшифровки во внешние AI-сервисы.

## Состояние репозитория

На старте папка проекта была пустой, без `.git`, `AGENTS.md` и `.openai/hosting.json`. Первый этап создал рабочий каркас: FastAPI backend, SQLite-модели, Alembic-миграцию, импорт папки сезона, fingerprint/dedupe, безопасную обёртку ffprobe, persistent job queue, system-check и минимальную русскую React-панель.

Второй этап добавил media pipeline: выбор русской аудио/субтитровой дорожки, атомарное извлечение mono WAV 16 kHz, создание proxy MP4, lazy-интеграцию faster-whisper, lazy-интеграцию PySceneDetect AdaptiveDetector, сохранение transcript word timestamps и scene boundaries, а также stub-компоненты для тестов без GPU и тяжёлых моделей.

Третий-пятый этапы добавили MVP-путь от расшифровки к готовому ролику: локальный llama.cpp HTTP adapter + stub, строгие Pydantic JSON-схемы, карту эпизода, генерацию/валидацию/дедупликацию кандидатов, карточки кандидатов в UI, review, русские SRT/ASS, FFmpeg render 1080x1920, export metadata/cover и Telegram long polling adapter с whitelist и идемпотентными callback-действиями.

Следующий срез добавил первые продуктовые фичи: автоматический режим, локально сохраняемые настройки UI, сезонную очередь с pause/resume/run-next/cancel/retry и улучшенный render с пресетами YouTube Shorts / Instagram Reels, NVENC auto-detect, экспортом без субтитров и опциональным двухпроходным loudnorm.

## Быстрый старт Windows

Требуется Python 3.11.x, Node.js 22+ или 24+, FFmpeg/ffprobe в `PATH`.

```powershell
Copy-Item .env.example .env
.\scripts\setup.ps1
.\scripts\check_system.ps1
.\scripts\run.ps1
```

Панель откроется по адресу `http://127.0.0.1:8090`.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m pytest
Push-Location frontend
npm run build
Pop-Location
.\scripts\check_system.ps1
```

## Безопасность исходников

Импорт открывает видео только для чтения. Оригинальные серии не копируются целиком, не изменяются и не удаляются. Удаление в UI на следующих этапах должно касаться только производных cache/output-файлов и требовать подтверждения.

## Fingerprint

Для многогигабайтных файлов полный SHA-256 слишком дорог на каждом импорте. В MVP используется устойчивый fingerprint из размера файла, `mtime_ns` и SHA-256 выборок: начало, середина и конец файла по 1 MiB. Это быстро выявляет дубликаты в обычном локальном сезоне. Если файл был перекодирован или изменён без смены видимых метаданных, fingerprint может измениться; это приемлемо для MVP и задокументировано как компромисс между скоростью и надёжностью.

## Команды API первого этапа

- `GET /api/system-check` - проверка Python, FFmpeg, ffprobe, NVIDIA CLI, cache/output и свободного места.
- `POST /api/seasons/import` - импорт локальной папки сезона.
- `GET /api/seasons` - список сезонов и серий.
- `POST /api/episodes/{id}/probe` - ffprobe-метаданные серии.
- `POST /api/episodes/{id}/stage2` - выполнить media-анализ: audio/proxy/transcript/scenes.
- `POST /api/episodes/{id}/stage3` - построить outline и кандидаты.
- `GET /api/episodes/{id}/candidates` - список кандидатов серии.
- `POST /api/candidates/{id}/review` - принять или отклонить кандидата, изменить границы/crop.
- `POST /api/candidates/{id}/render` - экспортировать вертикальный MP4.
- `GET /api/exports` - список готовых экспортов.
- `GET /api/settings`, `PUT /api/settings` - локальные настройки UI.
- `POST /api/seasons/{id}/enqueue` - поставить сезон в очередь, включая auto-режим.
- `POST /api/queue/run-next` - выполнить следующую задачу очереди.
- `POST /api/queue/pause`, `POST /api/queue/resume` - управление очередью.
- `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry` - отмена и повтор задачи.
- `POST /api/episodes/{id}/auto-export` - принять и экспортировать кандидаты выше порога.
- `POST /api/episodes/{id}/enqueue` - идемпотентная постановка анализа в очередь.
- `POST /api/jobs/recover` - восстановление running-задач после рестарта.

## Media Pipeline MVP

По умолчанию `SERIALCUTS_ASR_ADAPTER=stub`, чтобы можно было проверить конвейер без скачивания модели. Для реального распознавания:

```env
SERIALCUTS_ASR_ADAPTER=faster-whisper
SERIALCUTS_ASR_MODEL_NAME=large-v3-turbo
SERIALCUTS_ASR_COMPUTE_TYPE=int8_float16
SERIALCUTS_ASR_FALLBACK_COMPUTE_TYPE=int8
```

FFmpeg-команды строятся только как массив аргументов и пишут во временный файл рядом с целевым, затем атомарно переименовывают результат. Исходное видео передаётся FFmpeg как входной файл и не изменяется.

## LLM и кандидаты

По умолчанию `SERIALCUTS_LLM_ADAPTER=stub`. Для локального llama.cpp:

```env
SERIALCUTS_LLM_ADAPTER=llama-cpp-http
SERIALCUTS_LLM_BASE_URL=http://127.0.0.1:8081
SERIALCUTS_LLM_MODEL_HINT=Qwen3-8B-Instruct-GGUF-Q4
```

Адаптер ожидает endpoint `/completion`, совместимый с llama.cpp server. Ответ кандидатов валидируется через Pydantic и затем детерминированно корректируется по словам/сценам.

## Auto Mode И Очередь

В панели можно поставить весь сезон в очередь обычным режимом или `Auto`. `run-next` выполняет один job: Stage 2, Stage 3 и, если включён auto, экспортирует кандидаты выше `auto_score_threshold`, но не больше `max_clips_per_episode`. Очередь можно поставить на паузу и продолжить; ETA строится по фактическим длительностям завершённых job.

## Render

Доступны пресеты:

- `youtube_shorts`: 1080x1920, H.264, AAC 160k.
- `instagram_reels`: 1080x1920, H.264, AAC 192k.

NVENC можно включить вручную или оставить auto-detect в backend. Экспорт без субтитров доступен отдельной кнопкой. Двухпроходный loudnorm включается настройкой `render_loudnorm_two_pass`; если анализ не дал валидный JSON, используется обычный безопасный loudnorm-фильтр.

## Telegram

Telegram-бот работает через long polling и требует whitelist:

```env
SERIALCUTS_TELEGRAM_BOT_TOKEN=<telegram_bot_token>
SERIALCUTS_TELEGRAM_ALLOWED_USER_IDS=111111111,222222222
```

Запуск:

```powershell
.\scripts\run_telegram.ps1
```

Callbacks `approve`, `reject`, `export` идемпотентны: повторное нажатие той же кнопки возвращает сохранённый результат операции.

## Удаление cache и моделей

Пока модели не скачиваются автоматически. Cache можно удалить вручную из папки, указанной в `SERIALCUTS_CACHE_DIR`; готовые ролики лежат отдельно в `SERIALCUTS_OUTPUT_DIR`. Не удаляйте папки с исходными сериями.
