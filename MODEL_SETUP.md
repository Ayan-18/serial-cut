# Установка моделей

SerialCuts не скачивает многогигабайтные модели молча. На следующих этапах будет добавлена отдельная команда установки моделей с показом размера и явным подтверждением.

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
- CTranslate2: `4.6.0`; актуальная GPU-ветка требует CUDA 12 и cuDNN 9.
- React: `19.2.8`.
- Vite: `8.1.0`.
- TypeScript: `5.9.2`.
- Vitest: `4.1.11`.

Источники: [FastAPI/PyPI](https://pypi.org/project/fastapi/), [SQLAlchemy downloads](https://www.sqlalchemy.org/download.html), [Alembic/PyPI](https://pypi.org/project/alembic/), [faster-whisper README](https://github.com/SYSTRAN/faster-whisper), [PySceneDetect download](https://www.scenedetect.com/download/), [React versions](https://react.dev/versions), [Vite 8.1](https://vite.dev/blog/announcing-vite8-1), [TypeScript 5.9](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-9.html), [Vitest](https://vitest.dev/).

## ASR

Рекомендуемый профиль:

- модель: `large-v3-turbo` для faster-whisper;
- язык: `ru`;
- timestamps: segment + word timestamps;
- VAD: включён;
- GPU compute: сначала `int8_float16`, fallback `int8` при нехватке VRAM.

Для Windows GPU-режима проверьте CUDA 12/cuDNN 9. Если на машине установлены более старые CUDA/cuDNN, нужно закрепить совместимый `ctranslate2` согласно документации faster-whisper.

В текущем коде реальный adapter включается через `.env`:

```env
SERIALCUTS_ASR_ADAPTER=faster-whisper
```

Без этой настройки используется `stub`, чтобы проверить UI, БД и media-стадии без скачивания модели.

## LLM

Рекомендуемый профиль:

- `Qwen3` instruct-класса 8B в GGUF Q4;
- `llama.cpp` HTTP server только на `127.0.0.1`;
- режим без thinking;
- анализ длинной расшифровки иерархически.

В MVP adapter использует llama.cpp-compatible `/completion`:

```env
SERIALCUTS_LLM_ADAPTER=llama-cpp-http
SERIALCUTS_LLM_BASE_URL=http://127.0.0.1:8081
```

Для проверки без модели оставьте `SERIALCUTS_LLM_ADAPTER=stub`.

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
