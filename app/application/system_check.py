from __future__ import annotations

import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.processes import run_process


@dataclass(frozen=True)
class CheckItem:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True)
class SystemCheckReport:
    ok: bool
    items: list[CheckItem]


def run_system_check(settings: Settings | None = None) -> SystemCheckReport:
    settings = settings or get_settings()
    items = [
        _python_check(),
        _tool_check("ffmpeg", settings.ffmpeg_path, ["-version"]),
        _tool_check("ffprobe", settings.ffprobe_path, ["-version"]),
        _tool_check("nvidia-smi", "nvidia-smi", ["--query-gpu=name,memory.total", "--format=csv,noheader"]),
        _directory_check("cache", settings.cache_dir),
        _directory_check("output", settings.output_dir),
        _disk_check(settings.cache_dir),
    ]
    required_ok = all(item.ok for item in items if item.name not in {"nvidia-smi"})
    return SystemCheckReport(ok=required_ok, items=items)


def report_as_dict(report: SystemCheckReport) -> dict:
    return {"ok": report.ok, "items": [asdict(item) for item in report.items]}


def _python_check() -> CheckItem:
    version = sys.version_info
    ok = (version.major, version.minor) >= (3, 11)
    return CheckItem(
        name="python",
        ok=ok,
        message=f"{version.major}.{version.minor}.{version.micro}; требуется 3.11+",
    )


def _tool_check(name: str, executable: str, version_args: list[str]) -> CheckItem:
    resolved = shutil.which(executable) if executable == Path(executable).name else executable
    if not resolved:
        return CheckItem(name=name, ok=False, message=f"{executable} не найден в PATH")
    try:
        result = run_process([executable, *version_args], timeout_seconds=15)
    except Exception as exc:
        return CheckItem(name=name, ok=False, message=str(exc))
    first_line = (result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else ""
    return CheckItem(name=name, ok=result.returncode == 0, message=first_line or f"код {result.returncode}")


def _directory_check(name: str, path: Path) -> CheckItem:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return CheckItem(name=f"{name}_dir", ok=True, message=str(path.resolve(strict=False)))
    except Exception as exc:
        return CheckItem(name=f"{name}_dir", ok=False, message=str(exc))


def _disk_check(path: Path) -> CheckItem:
    try:
        usage = shutil.disk_usage(path.resolve(strict=False))
        free_gb = usage.free / (1024**3)
        return CheckItem(name="free_space", ok=free_gb >= 10, message=f"{free_gb:.1f} GB свободно")
    except Exception as exc:
        return CheckItem(name="free_space", ok=False, message=str(exc))


def main() -> int:
    report = run_system_check()
    for item in report.items:
        status = "OK" if item.ok else "FAIL"
        print(f"[{status}] {item.name}: {item.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

