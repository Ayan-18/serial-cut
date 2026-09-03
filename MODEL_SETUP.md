# Установка моделей

SerialCuts не скачивает многогигабайтные модели молча. Установщик сначала показывает размер и
требует явное подтверждение. Все модели остаются в `data/models`; исходные видео, аудио и
расшифровки не отправляются во внешние AI-сервисы.

## Установка

```powershell
winget install --exact --id ggml.llamacpp
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_models.ps1
```

Будут скачаны:

- `Systran/faster-whisper-small`, около 486 MB, закреплённая ревизия;
- `ggml-org/Qwen3-4B-GGUF`, файл `Qwen3-4B-Q4_K_M.gguf`, около 2.5 GB.

Для Qwen установщик вычисляет SHA-256 и принимает только
`ab27b9bfa375a178d6cba48f3ad892b94b7739659dcc7aae8058ce0ffed6b328`. Это файлы весов
моделей, а не исполняемые программы. Исполняемый `llama-server` устанавливается отдельно через
официальный пакет llama.cpp в winget.

## Выбранные версии библиотек

Проверено по официальным страницам и PyPI на 2026-08-29:

- Python: `>=3.11,<3.13`.
- FastAPI: `0.141.1`.
- Uvicorn: `0.52.4`.
- Pydantic: `2.13.4`.
- SQLAlchemy: `2.0.52`; ветка `2.1` пока beta, поэтому для MVP выбрана текущая стабильная `2.0`.
- Alembic: `1.19.1`.
- PySceneDetect: `0.7.1`, пакет `scenedetect-headless`.
- faster-whisper: `1.2.0`.
- CTranslate2: `4.6.3`; `4.6.0` падал на Windows с `No module named 'pkg_resources'` при
  setuptools ≥ 81 — `4.6.3` определяет каталог DLL через `importlib.resources`. Актуальная
  GPU-ветка требует CUDA 12 и cuDNN 9.
- React: `19.2.8`.
- Vite: `8.1.0`.
- TypeScript: `5.9.2`.
- Vitest: `4.1.11`.

Источники: [FastAPI/PyPI](https://pypi.org/project/fastapi/), [SQLAlchemy downloads](https://www.sqlalchemy.org/download.html), [Alembic/PyPI](https://pypi.org/project/alembic/), [faster-whisper README](https://github.com/SYSTRAN/faster-whisper), [PySceneDetect download](https://www.scenedetect.com/download/), [React versions](https://react.dev/versions), [Vite 8.1](https://vite.dev/blog/announcing-vite8-1), [TypeScript 5.9](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-9.html), [Vitest](https://vitest.dev/).

## ASR

Рабочий профиль для этой машины:

- модель: локальная `faster-whisper-small`;
- язык: `ru`;
- timestamps: segment + word timestamps;
- VAD: включён;
- CPU compute: `int8`.

CPU выбран как надёжный профиль для GTX 1660 SUPER: современный faster-whisper GPU-режим требует
совместимые CUDA 12 и cuDNN 9. Код умеет попробовать CUDA и автоматически перейти на CPU `int8`,
если в `.env` задано `SERIALCUTS_ASR_DEVICE=auto`.

В текущем коде реальный adapter включается через `.env`:

```env
SERIALCUTS_ASR_ADAPTER=faster-whisper
SERIALCUTS_ASR_MODEL_NAME=./data/models/faster-whisper-small
SERIALCUTS_ASR_DEVICE=cpu
```

Без этой настройки используется `stub`, чтобы проверить UI, БД и media-стадии без скачивания модели.

## LLM

Рабочий профиль:

- `Qwen3-4B` в GGUF `Q4_K_M`;
- `llama.cpp` HTTP server только на `127.0.0.1`;
- режим без thinking;
- анализ расшифровки тремя временными частями.

Адаптер использует llama.cpp-compatible `/v1/chat/completions` и строгую JSON Schema:

```env
SERIALCUTS_LLM_ADAPTER=llama-cpp-http
SERIALCUTS_LLM_BASE_URL=http://127.0.0.1:8081
```

Для проверки без модели оставьте `SERIALCUTS_LLM_ADAPTER=stub`.

## Запуск

Одна команда запускает скрытый `llama-server`, ждёт его готовности, применяет миграции и запускает
SerialCuts:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_local.ps1
```

Для диагностики LLM отдельно используйте `scripts/run_llm.ps1`. После первого скачивания интернет
для распознавания, анализа и рендера не нужен.

## TTS (озвучка StoryArc)

По умолчанию `SERIALCUTS_TTS_ADAPTER=silero` — нейросетевой русский голос Silero v4_ru, работает на
CPU и не занимает VRAM. Нужен опциональный пакет `torch` и модель ~60 МБ:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[tts]"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_tts_model.ps1
```

Модель качается из `https://models.silero.ai/models/tts/ru/v4_ru.pt` в `data/models/tts/` и
проверяется попыткой загрузки через `torch.package`. Голоса: `eugene`, `aidar` (муж.), `baya`,
`kseniya`, `xenia` (жен.). Голос диктора задаётся `SERIALCUTS_TTS_NARRATOR_VOICE`, голос конкретного
героя — в карточке персонажа (или авто по полу). Альтернативы: `windows-sapi` (голос Windows, нужен
русский голос в системе) и `stub`. Это синтетический голос, не клонирование актёра.

## VLM

Опционально:

- модель класса `Qwen3-VL 4B GGUF Q4`;
- запуск только для top-кандидатов;
- не держать одновременно с ASR/LLM в VRAM.

## Диагностика

```powershell
.\scripts\check_system.ps1
```

Проверка должна показать Python 3.11+, FFmpeg, ffprobe, `nvidia-smi`, доступность cache/output и свободное место.

На проверочном эпизоде длительностью 11:42 Stage 2 занял около 3-4 минут на CPU и сохранил 137
реплик и 194 сцены. Stage 3 занял около минуты на GTX 1660 SUPER и выдал 5 кандидатов из разных
частей эпизода. Время зависит от длительности видео и железа.
