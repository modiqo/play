from __future__ import annotations

import unittest
import io
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.release import publish_play

from scripts.release.publish_play import (
    ReleaseError,
    release_tag,
    replace_selector,
    selector_release,
)


SELECTOR = """#!/bin/sh
set -eu
release=v0.4.56

curl "https://example.test/${release}/install.sh" \\
  | env PLAY_INSTALL_REF="${release}" PLAY_INSTALL_CHANNEL=playoffs sh
"""


class ReleasePublishTest(unittest.TestCase):
    def test_assets_staging_preserves_other_installers_and_rejects_path_escape(self) -> None:
        def archive(name, body):
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
                member = tarfile.TarInfo(name)
                member.size = len(body)
                bundle.addfile(member, io.BytesIO(body))
            return buffer.getvalue()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            publish_play.stage_assets(target, archive("repo/install", b"original Rote installer"))
            self.assertEqual(b"original Rote installer", (target / "install").read_bytes())
            with self.assertRaises(ReleaseError):
                publish_play.stage_assets(target, archive("repo/../escape", b"bad"))

    def test_publication_changes_only_staged_play_selector_and_never_pushes_assets_repo(self) -> None:
        def assets(path):
            (path / "playoffs").mkdir()
            (path / "playoffs/install.sh").write_text(SELECTOR)
            (path / "install").write_text("existing Rote installer")
            return "b" * 40
        def execute(command, *, cwd):
            if "deploy" in command:
                staged = Path(command[command.index("deploy") + 1])
                self.assertEqual("v0.4.102", selector_release((staged / "playoffs/install.sh").read_text()))
                self.assertEqual("existing Rote installer", (staged / "install").read_text())
                return "https://abc123.getrote-dev.pages.dev"
            return ""
        with (
            patch.object(publish_play, "validate_play_release", return_value=("0.4.102", "v0.4.102")),
            patch.object(publish_play.shutil, "which", return_value="/bin/npx"),
            patch.object(publish_play, "git", return_value="a" * 40) as git,
            patch.object(publish_play, "download_assets", side_effect=assets),
            patch.object(publish_play, "run", side_effect=execute),
            patch.object(publish_play, "wait_for_public_selector") as verify,
        ):
            result = publish_play.publish(Path("/play"))
        git.assert_called_once_with(Path("/play"), "rev-parse", "HEAD")
        verify.assert_called_once_with("v0.4.102")
        self.assertEqual("published", result["status"])

    def test_release_tag_requires_semantic_version(self) -> None:
        self.assertEqual("v0.4.58", release_tag("0.4.58\n"))
        with self.assertRaises(ReleaseError):
            release_tag("0.4")

    def test_selector_release_requires_one_assignment(self) -> None:
        self.assertEqual("v0.4.56", selector_release(SELECTOR))
        with self.assertRaises(ReleaseError):
            selector_release("#!/bin/sh\n")
        with self.assertRaises(ReleaseError):
            selector_release(SELECTOR + "release=v0.4.57\n")

    def test_replace_selector_changes_only_the_release(self) -> None:
        updated = replace_selector(SELECTOR, "v0.4.58")
        self.assertEqual("v0.4.58", selector_release(updated))
        self.assertIn("PLAY_INSTALL_CHANNEL=playoffs", updated)
        self.assertEqual(SELECTOR, replace_selector(SELECTOR, "v0.4.56"))


if __name__ == "__main__":
    unittest.main()
