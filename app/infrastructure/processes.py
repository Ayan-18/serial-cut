from __future__ import annotations

import subprocess
from dataclasses import dataclass
from time import monotonic
from typing import Sequence


@dataclass(frozen=True)
class ProcessResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


class ProcessCancelledError(RuntimeError):
    pass


def run_process(args: Sequence[str], timeout_seconds: int) -> ProcessResult:
    completed = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        shell=False,
        check=False,
    )
    return ProcessResult(
        args=list(args),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def run_process_cancellable(
    args: Sequence[str],
    timeout_seconds: int,
    cancel_check,
) -> ProcessResult:
    command = list(args)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    started = monotonic()
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.35)
            return ProcessResult(command, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            if cancel_check():
                process.terminate()
                try:
                    process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                raise ProcessCancelledError("Операция остановлена пользователем")
            if monotonic() - started > timeout_seconds:
                process.kill()
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(command, timeout_seconds, stdout, stderr)

