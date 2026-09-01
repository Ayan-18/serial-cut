from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from app.infrastructure.logging_config import current_log_path

_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
    r"(?P<logger>\S+):\s?(?P<message>.*)$"
)
_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_MAX_LINES = 2000


@dataclass(frozen=True)
class LogEntry:
    timestamp: str | None
    level: str
    logger: str
    message: str


@dataclass(frozen=True)
class LogTail:
    path: str
    exists: bool
    size_bytes: int
    returned: int
    entries: list[LogEntry]


def _min_level_index(level: str | None) -> int:
    if not level:
        return 0
    try:
        return _LEVELS.index(level.upper())
    except ValueError:
        return 0


def read_log_tail(
    lines: int = 200,
    min_level: str | None = None,
    search: str | None = None,
    log_path: Path | None = None,
) -> LogTail:
    path = log_path or current_log_path()
    limit = max(1, min(_MAX_LINES, lines))
    if not path.exists():
        return LogTail(path=str(path), exists=False, size_bytes=0, returned=0, entries=[])

    raw_tail: deque[str] = deque(maxlen=_MAX_LINES)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            raw_tail.append(raw.rstrip("\n"))

    threshold = _min_level_index(min_level)
    needle = search.lower() if search else None
    parsed: list[LogEntry] = []
    for raw in raw_tail:
        match = _LINE_RE.match(raw)
        if match:
            entry = LogEntry(
                timestamp=match.group("ts"),
                level=match.group("level"),
                logger=match.group("logger"),
                message=match.group("message"),
            )
        elif parsed:
            # Continuation line (e.g. a traceback) belongs to the previous entry.
            previous = parsed[-1]
            parsed[-1] = LogEntry(
                previous.timestamp,
                previous.level,
                previous.logger,
                f"{previous.message}\n{raw}",
            )
            continue
        else:
            entry = LogEntry(timestamp=None, level="INFO", logger="-", message=raw)
        parsed.append(entry)

    filtered = [
        entry
        for entry in parsed
        if _min_level_index(entry.level) >= threshold
        and (needle is None or needle in entry.message.lower() or needle in entry.logger.lower())
    ]
    tail = filtered[-limit:]
    return LogTail(
        path=str(path),
        exists=True,
        size_bytes=path.stat().st_size,
        returned=len(tail),
        entries=tail,
    )
