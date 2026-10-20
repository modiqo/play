"""`play update` for Play installs made by Play 0.4.105 and earlier.

Those releases bundle an install.sh that downloads Play `main` and runs
`python3 scripts/bin/play-bootstrap install ...` from it, under whatever
Python the user has. Play is now installed by rote, so this module is
stdlib-only and does one of two things:

- rote has `install play`: run it. rote takes over the old install.
- otherwise: run the bootstrap of LEGACY_RELEASE, the last Play-owned
  installer, with the same arguments, so the update works as before. It may
  install rote; ROTE_NO_PLAY keeps a new rote installer from installing a
  second, rote-owned Play beside it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath


LEGACY_RELEASE = "v0.4.105"
LEGACY_ARCHIVE_URL = f"https://github.com/modiqo/play/archive/refs/tags/{LEGACY_RELEASE}.tar.gz"


def _log(message: str) -> None:
    print(f"play update: {message}", file=sys.stderr, flush=True)


def rote_installs_play(rote: str) -> bool:
    """A rote without `install play` rejects it with a nonzero exit."""
    try:
        probe = subprocess.run(
            [rote, "install", "play", "--help"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def rote_command(rote: str, arguments: Sequence[str]) -> list[str]:
    """Only `--yes` carries over; rote detects and wires harnesses itself."""
    return [rote, "install", "play", *(["--yes"] if "--yes" in arguments else [])]


def extract(archive: Path, destination: Path) -> None:
    """Extract a GitHub archive without its top-level directory."""
    with tarfile.open(archive, "r:gz") as bundle:
        roots: set[str] = set()
        members: list[tarfile.TarInfo] = []
        for member in bundle.getmembers():
            parts = PurePosixPath(member.name).parts
            if not parts or member.name.startswith("/") or ".." in parts:
                raise ValueError(f"unsafe path in Play archive: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"unsupported entry in Play archive: {member.name}")
            roots.add(parts[0])
            if len(parts) > 1:
                member.name = str(PurePosixPath(*parts[1:]))
                members.append(member)
        if len(roots) != 1:
            raise ValueError("Play archive must contain one repository root")
        if hasattr(tarfile, "data_filter"):
            bundle.extractall(destination, members=members, filter="data")
        else:
            bundle.extractall(destination, members=members)


def run_legacy(arguments: Sequence[str]) -> int:
    curl = shutil.which("curl")
    if curl is None:
        _log("curl is required to download the Play installer")
        return 1
    with tempfile.TemporaryDirectory(prefix="play-legacy-") as temporary:
        root = Path(temporary)
        archive = root / "play.tar.gz"
        source = root / "source"
        download = subprocess.run(
            [curl, "--proto", "=https", "--tlsv1.2", "-fsSL", LEGACY_ARCHIVE_URL, "-o", str(archive)],
            stdin=subprocess.DEVNULL,
            check=False,
        )
        if download.returncode != 0:
            _log(f"could not download {LEGACY_ARCHIVE_URL}")
            return 1
        source.mkdir()
        try:
            extract(archive, source)
        except (tarfile.TarError, ValueError) as error:
            _log(str(error))
            return 1
        bootstrap = source / "scripts" / "bin" / "play-bootstrap"
        if not bootstrap.is_file():
            _log(f"the Play {LEGACY_RELEASE} archive has no installer")
            return 1
        environment = {**os.environ, "ROTE_NO_PLAY": "1"}
        return subprocess.run(
            [sys.executable, str(bootstrap), *arguments], env=environment, check=False
        ).returncode


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    rote = shutil.which("rote")
    if rote is not None and rote_installs_play(rote):
        _log("Play is now installed by rote. Running: rote install play")
        return subprocess.run(rote_command(rote, arguments), check=False).returncode
    _log(f"rote cannot install Play here. Running the Play {LEGACY_RELEASE} installer")
    return run_legacy(arguments)
