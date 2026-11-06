"""Write pack/ as the release tarball rote's `play` known pack pins.

rote reads `pack.ron` at the tarball's root and pins the tarball's SHA-256,
so the bytes depend only on the files: sorted entries, no owners, fixed
modes, and zero timestamps in both tar and gzip.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "pack"
ASSET = "play-pack.tar.gz"


def tarball(pack: Path) -> bytes:
    files = sorted(path for path in pack.rglob("*") if path.is_file())
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in files:
            data = path.read_bytes()
            info = tarfile.TarInfo(path.relative_to(pack).as_posix())
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    return gzip.compress(buffer.getvalue(), compresslevel=9, mtime=0)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(ASSET))
    args = parser.parse_args(argv)
    data = tarball(PACK)
    args.output.write_bytes(data)
    receipt = {"asset": str(args.output), "sha256": hashlib.sha256(data).hexdigest()}
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
