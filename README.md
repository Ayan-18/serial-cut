# SerialCuts

SerialCuts - локальное Windows-приложение для поиска осмысленных фрагментов в сериях с русской озвучкой и подготовки вертикальных MP4 для YouTube Shorts / Instagram Reels. MVP не публикует ролики автоматически и не отправляет исходные видео, кадры, аудио или расшифровки во внешние AI-сервисы.

## Состояние репозитория

На старте папка проекта была пустой, без `.git`, `AGENTS.md` и `.openai/hosting.json`. Первый этап создал рабочий каркас: FastAPI backend, SQLite-модели, Alembic-миграцию, импорт папки сезона, fingerprint/dedupe, безопасную обёртку ffprobe, persistent job queue, system-check и минимальную русскую React-панель.

Второй этап добавил media pipeline: выбор русской аудио/субтитровой дорожки, атомарное извлечение mono WAV 16 kHz, создание proxy MP4, lazy-интеграцию faster-whisper, lazy-интеграцию PySceneDetect AdaptiveDetector, сохранение transcript word timestamps и scene boundaries, а также stub-компоненты для тестов без GPU и тяжёлых моделей.

Третий-пятый этапы добавили MVP-путь от расшифровки к готовому ролику: локальный llama.cpp HTTP adapter + stub, строгие Pydantic JSON-схемы, карту эпизода, генерацию/валидацию/дедупликацию кандидатов, карточки кандидатов в UI, review, русские SRT/ASS, FFmpeg render 1080x1920, export metadata/cover и Telegram long polling adapter с whitelist и идемпотентными callback-действиями.

Следующий срез добавил первые продуктовые фичи: автоматический режим, локально сохраняемые настройки UI, сезонную очередь с pause/resume/run-next/cancel/retry и улучшенный render с пресетами YouTube Shorts / Instagram Reels, NVENC auto-detect, экспортом без субтитров и опциональным двухпроходным loudnorm.

Текущий продуктовый экран добавляет фоновую очередь, вертикальный предпросмотр выбранного отрывка,
ручной редактор субтитров и кадрирования, локальный поиск лиц, эвристические метки говорящих,
фильтры кандидатов, диагностику моделей, безопасную очистку кэша и галерею готовых экспортов.

## Быстрый старт Windows с реальными моделями

Требуется Python 3.11.x, Node.js 22+ или 24+, FFmpeg/ffprobe и `llama-server` в `PATH`.
PowerShell-команды ниже используют разовый обход Execution Policy и не меняют системную политику.

```powershell
Copy-Item .env.example .env
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
winget install --exact --id ggml.llamacpp
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_models.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_system.ps1
```

Чтобы включить реальные адаптеры, задайте в `.env`:

```env
SERIALCUTS_ASR_ADAPTER=faster-whisper
SERIALCUTS_ASR_MODEL_NAME=./data/models/faster-whisper-small
SERIALCUTS_ASR_DEVICE=cpu
SERIALCUTS_LLM_ADAPTER=llama-cpp-http
```

Запуск приложения и локальной Qwen одной командой:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_local.ps1
```

Откройте `http://127.0.0.1:8090`. Модель Qwen запускается скрыто только на `127.0.0.1` и
останавливается вместе с приложением. Логи находятся в `data/logs`. Вариант без моделей для
быстрой проверки интерфейса остаётся доступен через адаптеры `stub` и `scripts/run.ps1`.

Можно также дважды щёлкнуть `Start SerialCuts.cmd`. Скрипт `scripts/create_shortcut.ps1` создаёт
ярлык `SerialCuts` на рабочем столе; на настроенном компьютере он уже создан.

## Работа Через Codex На Двух Компьютерах

Общий контекст проекта хранится в GitHub, `AGENTS.md`, `WORKLOG.md` и документации. Перед работой на ноутбуке или компьютере делайте `git pull --ff-only`, после завершения - обновляйте `WORKLOG.md`, коммитьте и пушьте изменения. Подробная инструкция: `docs/CODEX_SYNC.md`.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m pytest
Push-Location frontend
npm run build
Pop-Location
.\scripts\check_system.ps1
```

## Безопасность исходников

Импорт открывает видео только для чтения. Оригинальные серии не копируются целиком, не изменяются и не удаляются. Кнопка очистки в UI удаляет только производные файлы внутри настроенной папки cache и требует подтверждения; готовые ролики и исходные серии она не затрагивает.

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
- `GET`, `PUT`, `DELETE /api/candidates/{id}/subtitles` - получить, сохранить или пересобрать субтитры кандидата.
- `POST /api/candidates/{id}/auto-crop` - локально оценить положение лиц в отрывке.
- `POST /api/candidates/{id}/render-job` - поставить рендер в фоновую очередь.
- `GET /api/exports` - список готовых экспортов.
- `GET /api/exports/{id}/file`, `GET /api/exports/{id}/cover` - просмотр результата и обложки.
- `POST /api/exports/{id}/open-folder` - открыть папку готового файла в Windows.
- `GET`, `DELETE /api/cache` - размер и подтверждённая безопасная очистка кэша.
- `GET /api/model-diagnostics` - доступность локальных Whisper и Qwen.
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
SERIALCUTS_ASR_MODEL_NAME=./data/models/faster-whisper-small
SERIALCUTS_ASR_DEVICE=cpu
SERIALCUTS_ASR_COMPUTE_TYPE=int8
SERIALCUTS_ASR_FALLBACK_COMPUTE_TYPE=int8
```

FFmpeg-команды строятся только как массив аргументов и пишут во временный файл рядом с целевым, затем атомарно переименовывают результат. Исходное видео передаётся FFmpeg как входной файл и не изменяется.

## LLM и кандидаты

По умолчанию `SERIALCUTS_LLM_ADAPTER=stub`. Для локального llama.cpp:

```env
SERIALCUTS_LLM_ADAPTER=llama-cpp-http
SERIALCUTS_LLM_BASE_URL=http://127.0.0.1:8081
SERIALCUTS_LLM_MODEL_HINT=Qwen3-4B-GGUF-Q4_K_M
```

Адаптер использует локальный endpoint `/v1/chat/completions` с JSON Schema. Расшифровка делится
на три временные части, чтобы кандидаты искались по всему эпизоду, а не только в начале. Ответы
валидируются через Pydantic, короткие границы расширяются до настроенного минимума и затем
корректируются по словам/сценам.

## Auto Mode И Очередь

В панели можно поставить серию или весь сезон в очередь обычным режимом либо `Auto`. Фоновый worker
сам берёт следующую задачу, восстанавливает прерванные задачи после запуска и показывает этап,
прогресс, ошибку и ETA. Очередь можно поставить на паузу, безопасно остановить задачу или повторить
ошибочную. `run-next` оставлен для ручной диагностики и тестов. Рендер также идёт через очередь,
поэтому во время него интерфейс остаётся доступен.

## Render

Доступны пресеты:

- `youtube_shorts`: 1080x1920, H.264, AAC 160k.
- `instagram_reels`: 1080x1920, H.264, AAC 192k.

NVENC можно включить вручную или оставить auto-detect в backend. Экспорт без субтитров доступен отдельной кнопкой. Двухпроходный loudnorm включается настройкой `render_loudnorm_two_pass`; если анализ не дал валидный JSON, используется обычный безопасный loudnorm-фильтр.

Субтитры синхронизируются по таймкодам распознанных слов, выводятся максимум в две строки и
рассчитаны на кадр 1080x1920. Размер шрифта регулируется в панели; значение по умолчанию — 48.
Повторное нажатие кнопки рендера пересобирает существующий производный клип. Если NVENC установлен,
но драйвер не поддерживает нужную FFmpeg API, рендер автоматически повторяется через CPU `libx264`.

Редактор кандидата проигрывает только выбранный временной диапазон, показывает субтитры поверх
вертикального предпросмотра и позволяет менять текст, тайминги и подпись говорящего. Кадр можно
сместить, увеличить или автоматически центрировать по найденным лицам. Детекция лиц и кластеризация
голосов выполняются локально эвристическими алгоритмами; результаты рекомендуется проверить перед
финальным рендером.

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

## Cache и модели

Модели скачиваются только после явного подтверждения командой `scripts/install_models.ps1` и
хранятся в `data/models` (около 3 GB). В разделе «Готовность системы» виден статус обоих локальных
адаптеров. Cache можно очистить там же после подтверждения; готовые ролики лежат отдельно в
`SERIALCUTS_OUTPUT_DIR`. Не удаляйте папки с исходными сериями.
