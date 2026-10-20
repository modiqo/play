from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bin" / "play-bootstrap"


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


class LegacyUpdateTest(unittest.TestCase):
    """Play <= 0.4.105 `play update` downloads main and runs play-bootstrap."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.calls = self.base / "calls"
        self.archive = self.base / "legacy.tar.gz"
        _executable(
            self.bin / "curl",
            textwrap.dedent(
                f"""\
                #!/bin/sh
                echo curl >> '{self.calls}'
                while [ "$#" -gt 0 ]; do
                  [ "$1" = -o ] && cp '{self.archive}' "$2"
                  shift
                done
                """
            ),
        )
        self.legacy_archive(
            {
                "play-0.4.105/scripts/bin/play-bootstrap": textwrap.dedent(
                    f"""\
                    import os, sys
                    with open({str(self.calls)!r}, "a") as calls:
                        calls.write("legacy " + " ".join(sys.argv[1:])
                                    + " ROTE_NO_PLAY=" + os.environ.get("ROTE_NO_PLAY", "") + "\\n")
                    """
                )
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def legacy_archive(self, files: dict[str, str]) -> None:
        with tarfile.open(self.archive, "w:gz") as bundle:
            for name, content in files.items():
                data = content.encode()
                member = tarfile.TarInfo(name)
                member.size = len(data)
                bundle.addfile(member, io.BytesIO(data))

    def fake_rote(self, help_status: int) -> None:
        _executable(
            self.bin / "rote",
            textwrap.dedent(
                f"""\
                #!/bin/sh
                [ "$3" = --help ] && exit {help_status}
                echo "rote $*" >> '{self.calls}'
                """
            ),
        )

    def update(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = {
            key: value for key, value in os.environ.items() if key != "ROTE_NO_PLAY"
        }
        environment["PATH"] = f"{self.bin}:/usr/bin:/bin"
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def recorded(self) -> list[str]:
        return self.calls.read_text(encoding="utf-8").splitlines() if self.calls.exists() else []

    def test_hands_the_update_to_a_rote_that_installs_play(self) -> None:
        self.fake_rote(help_status=0)

        result = self.update("install", "--yes", "--harness", "codex", "--mode", "update")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["rote install play --yes"], self.recorded())

    def test_runs_the_last_play_owned_installer_when_rote_cannot_install_play(self) -> None:
        self.fake_rote(help_status=1)

        result = self.update("install", "--harness", "codex", "--mode", "update")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            ["curl", "legacy install --harness codex --mode update ROTE_NO_PLAY=1"],
            self.recorded(),
        )

    def test_refuses_an_archive_that_escapes_its_root(self) -> None:
        self.legacy_archive({"play-0.4.105/../escape": "x"})

        result = self.update("install")

        self.assertEqual(1, result.returncode)
        self.assertIn("unsafe path", result.stderr)
        self.assertEqual(["curl"], self.recorded())


if __name__ == "__main__":
    unittest.main()
