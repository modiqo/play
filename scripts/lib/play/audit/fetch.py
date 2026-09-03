"""Pull a Play the user has access to into a temporary location for auditing.

rote installs pulls under ``$ROTE_HOME/flows``. To audit without touching the
real store, a throwaway home is built that links every entry of the real home
except ``flows`` and ``workspaces``, so login, registry cache, and runtimes are
shared while the pull lands in the temporary tree. The directory is removed
after the audit unless the caller keeps it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_PULL_TIMEOUT_SECONDS = 90.0
_PRIVATE_ENTRIES = {"flows", "workspaces"}

Runner = Callable[[list[str], dict[str, str]], tuple[int, str, str]]


@dataclass
class Pulled:
    root: Path
    temp_home: Path
    owner: str
    name: str

    def cleanup(self) -> None:
        shutil.rmtree(self.temp_home, ignore_errors=True)


def _real_home() -> Path:
    override = os.environ.get("ROTE_HOME")
    return Path(override) if override else Path.home() / ".rote"


def _run(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    completed = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=_PULL_TIMEOUT_SECONDS, env=env)
    return completed.returncode, completed.stdout, completed.stderr


def temp_home() -> Path:
    home = Path(tempfile.mkdtemp(prefix="play-audit-"))
    real = _real_home()
    if real.is_dir():
        for entry in real.iterdir():
            if entry.name in _PRIVATE_ENTRIES or entry.name.startswith("."):
                continue
            try:
                os.symlink(entry, home / entry.name)
            except OSError:
                continue
    (home / "flows").mkdir(exist_ok=True)
    return home


def pull(owner: str, name: str, *, runner: Runner | None = None) -> tuple[Pulled | None, str | None]:
    """Pull ``owner/name`` into a temporary home. Returns (pulled, error)."""
    if shutil.which("rote") is None:
        return None, "rote is not on PATH"
    home = temp_home()
    env = {**os.environ, "ROTE_HOME": str(home), "ROTE_NO_HINTS": "1", "ROTE_FLOW_PROGRESS": "0"}
    argv = ["rote", "registry", "play", "pull", f"{owner}/{name}", "--yes", "--no-deps"]
    try:
        code, stdout, stderr = (runner or _run)(argv, env)
    except (OSError, subprocess.SubprocessError) as error:
        shutil.rmtree(home, ignore_errors=True)
        return None, f"rote registry play pull {owner}/{name}: {error}"
    root = home / "flows" / owner / name
    if code != 0 or not (root / "main.ts").is_file():
        detail = (stderr or stdout).strip()
        first = next((line.strip() for line in detail.splitlines() if line.strip()), f"exit {code}")
        shutil.rmtree(home, ignore_errors=True)
        return None, f"could not pull {owner}/{name}: {first}"
    return Pulled(root=root, temp_home=home, owner=owner, name=name), None
