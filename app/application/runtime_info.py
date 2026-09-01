from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version as _package_version
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.queue_control import get_queue_state
from app.workers.queue import queue_snapshot

# A fresh identifier per process start. The frontend compares it across polls to
# notice that the backend was restarted (and therefore the local API token and
# any in-memory state are stale).
BOOT_ID = uuid4().hex
STARTED_AT = datetime.now(timezone.utc)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def app_version() -> str:
    try:
        return _package_version("serialcuts")
    except PackageNotFoundError:
        pyproject = _PROJECT_ROOT / "pyproject.toml"
        if pyproject.exists():
            for line in pyproject.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("version") and "=" in stripped:
                    return stripped.split("=", 1)[1].strip().strip('"').strip("'")
        return "0.0.0"


@lru_cache(maxsize=1)
def git_commit() -> str | None:
    """Best-effort short commit read straight from .git, without spawning git."""
    head = _PROJECT_ROOT / ".git" / "HEAD"
    if not head.exists():
        return None
    try:
        content = head.read_text(encoding="utf-8").strip()
        if content.startswith("ref:"):
            ref = content.split(" ", 1)[1].strip()
            ref_path = _PROJECT_ROOT / ".git" / ref
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()[:12]
            packed = _PROJECT_ROOT / ".git" / "packed-refs"
            if packed.exists():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line.endswith(ref):
                        return line.split(" ", 1)[0][:12]
            return None
        return content[:12]
    except OSError:
        return None


def token_fingerprint(token: str) -> str:
    """Stable non-secret fingerprint of the current local API token."""
    return sha256(token.encode("utf-8")).hexdigest()[:12]


def _db_revision(session: Session) -> str | None:
    try:
        return session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # pragma: no cover - inspection helper only
        return None


def health_report(session: Session, api_token: str) -> dict:
    now = datetime.now(timezone.utc)
    snapshot = queue_snapshot(session)
    return {
        "ok": True,
        "service": "SerialCuts",
        "version": app_version(),
        "commit": git_commit(),
        "boot_id": BOOT_ID,
        "token_fingerprint": token_fingerprint(api_token),
        "started_at": STARTED_AT.isoformat(),
        "uptime_seconds": round((now - STARTED_AT).total_seconds(), 1),
        "db_revision": _db_revision(session),
        "queue": {
            "state": get_queue_state(session),
            "queued": snapshot.queued,
            "running": snapshot.running,
            "failed": snapshot.failed,
        },
    }


def version_report() -> dict:
    return {
        "service": "SerialCuts",
        "version": app_version(),
        "commit": git_commit(),
        "boot_id": BOOT_ID,
        "started_at": STARTED_AT.isoformat(),
    }
