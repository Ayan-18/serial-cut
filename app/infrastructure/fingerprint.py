from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


SAMPLE_SIZE = 1024 * 1024


@dataclass(frozen=True)
class FileFingerprint:
    value: str
    size_bytes: int
    modified_ns: int


def fingerprint_file(path: Path, sample_size: int = SAMPLE_SIZE) -> FileFingerprint:
    stat = path.stat()
    digest = sha256()
    digest.update(str(stat.st_size).encode("ascii"))
    digest.update(str(stat.st_mtime_ns).encode("ascii"))

    with path.open("rb") as handle:
        offsets = _sample_offsets(stat.st_size, sample_size)
        for offset in offsets:
            handle.seek(offset)
            digest.update(handle.read(sample_size))

    return FileFingerprint(
        value=digest.hexdigest(),
        size_bytes=stat.st_size,
        modified_ns=stat.st_mtime_ns,
    )


def _sample_offsets(size_bytes: int, sample_size: int) -> list[int]:
    if size_bytes <= sample_size:
        return [0]
    last = max(0, size_bytes - sample_size)
    middle = max(0, (size_bytes // 2) - (sample_size // 2))
    return sorted(set([0, middle, last]))

