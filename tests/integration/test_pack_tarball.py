from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github" / "release"))

from pack_tarball import tarball  # noqa: E402


class PackTarballTest(unittest.TestCase):
    """rote pins the tarball's SHA-256 and reads pack.ron at its root."""

    def test_same_files_give_the_same_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary)
            (pack / "copy").mkdir()
            (pack / "pack.ron").write_text("Pack()\n")
            (pack / "copy" / "journey.ftl").write_text("prompt-approve-run = Run?\n")
            first = tarball(pack)
            (pack / "pack.ron").touch()
            self.assertEqual(first, tarball(pack))

    def test_pack_ron_is_a_top_level_entry(self) -> None:
        with tarfile.open(fileobj=io.BytesIO(tarball(ROOT / "pack")), mode="r:gz") as archive:
            names = archive.getnames()

        self.assertIn("pack.ron", names)
        self.assertTrue(all(not name.startswith(("/", "./", "pack/")) for name in names), names)


if __name__ == "__main__":
    unittest.main()
