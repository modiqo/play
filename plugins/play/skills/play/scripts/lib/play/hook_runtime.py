"""Run passive hooks within one wall-clock budget, without installing packages."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys


HOOK_TIMEOUT_SECONDS = 3.0
WORKER_ARGUMENT = "--hook-worker"


def run_hook(script: Path, root: Path, argv: list[str], *, timeout_seconds: float = HOOK_TIMEOUT_SECONDS) -> int:
    # The installer owns dependencies. A prompt must never sync or download them.
    installed_python = root / ".venv" / "bin" / "python"
    interpreter = str(installed_python) if installed_python.is_file() else sys.executable
    try:
        worker = subprocess.Popen(
            [interpreter, str(script), WORKER_ARGUMENT, *argv],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return 0
    try:
        output, _ = worker.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        # Include rote and any other descendants; do not leave work behind on
        # every submitted prompt. Discard even partially written hook output.
        try:
            os.killpg(worker.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        worker.communicate()
        return 0
    if worker.returncode == 0 and output:
        sys.stdout.buffer.write(output)
    return 0
