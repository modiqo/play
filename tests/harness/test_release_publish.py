from __future__ import annotations

import unittest
import io
import subprocess
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

    def test_publication_isolates_environments_and_preserves_other_installers(self) -> None:
        def assets(path):
            (path / "playoffs").mkdir()
            (path / "playoffs/install.sh").write_text(SELECTOR)
            (path / "install").write_text("existing Rote installer")
            return "b" * 40
        def execute(command, *, cwd):
            if "deploy" in command:
                staged = Path(command[command.index("deploy") + 1])
                self.assertEqual(reference, selector_release((staged / "playoffs/install.sh").read_text()))
                self.assertEqual("existing Rote installer", (staged / "install").read_text())
                self.assertEqual(branch, command[command.index("--branch") + 1])
                self.assertEqual("a" * 40, command[command.index("--commit-hash") + 1])
                return "https://abc123.getrote-dev.pages.dev"
            return ""
        for environment, branch, reference, url in (
            ("production", "main", "v0.4.99", publish_play.PUBLIC_SELECTOR),
            ("staging", "staging", "a" * 40, "https://staging.getrote-dev.pages.dev/playoffs/install.sh"),
        ):
            with (
                self.subTest(environment=environment),
                patch.object(publish_play, "validate_play_release", return_value=("0.4.99", "v0.4.99")) as release,
                patch.object(publish_play, "validate_play_commit", return_value=("0.4.99", "a" * 40)) as commit,
                patch.object(publish_play.shutil, "which", return_value="/bin/npx"),
                patch.object(publish_play, "git", return_value="a" * 40) as git,
                patch.object(publish_play, "download_assets", side_effect=assets),
                patch.object(publish_play, "run", side_effect=execute),
                patch.object(publish_play, "wait_for_public_selector") as verify,
            ):
                result = publish_play.publish(Path("/play"), environment=environment)
            git.assert_called_once_with(Path("/play"), "rev-parse", "HEAD")
            verify.assert_called_once_with(reference, public_selector=url)
            self.assertEqual("published", result["status"])
            self.assertEqual(environment, result["environment"])
            self.assertEqual(reference, result["reference"])
            self.assertEqual(url, result["public_selector"])
            if environment == "staging":
                release.assert_not_called()
                commit.assert_called_once()
                self.assertIsNone(result["tag"])
            else:
                release.assert_called_once()
                commit.assert_not_called()
                self.assertEqual(reference, result["tag"])

    def test_verification_reads_only_the_selected_environment(self) -> None:
        url = "https://staging.getrote-dev.pages.dev/playoffs/install.sh"
        selector = replace_selector(SELECTOR, "a" * 40)
        with patch.object(publish_play, "fetch_text", return_value=selector) as fetch:
            self.assertEqual(selector, publish_play.wait_for_public_selector("a" * 40, public_selector=url))
        self.assertTrue(fetch.call_args.args[0].startswith(f"{url}?release-check="))

    def test_unknown_environment_is_rejected_before_any_deployment(self) -> None:
        with patch.object(publish_play, "run") as run:
            with self.assertRaises(ReleaseError):
                publish_play.publish(Path("/play"), environment="unknown")
        run.assert_not_called()

    def test_failed_validation_never_downloads_or_deploys_assets(self) -> None:
        with (
            patch.object(publish_play, "validate_play_release", side_effect=ReleaseError("missing tag")),
            patch.object(publish_play, "download_assets") as download,
            patch.object(publish_play, "run") as run,
        ):
            with self.assertRaisesRegex(ReleaseError, "missing tag"):
                publish_play.publish(Path("/play"))
        download.assert_not_called()
        run.assert_not_called()

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

    def test_selector_accepts_immutable_commits_but_rejects_mutable_or_unsafe_refs(self) -> None:
        self.assertEqual("a" * 40, selector_release(replace_selector(SELECTOR, "a" * 40)))
        for reference in ("main", "abc123", "v0.4.99\necho bad", "$(echo bad)"):
            with self.subTest(reference=reference), self.assertRaises(ReleaseError):
                replace_selector(SELECTOR, reference)


class DeploymentCheckoutTest(unittest.TestCase):
    """Exercise Git preconditions with a local origin and Actions-style detached HEAD."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.origin = self.root / "origin"
        self.checkout = self.root / "checkout"
        subprocess.run(["git", "init", "--initial-branch=main", str(self.origin)], check=True, capture_output=True)
        self.git(self.origin, "config", "user.email", "test@example.test")
        self.git(self.origin, "config", "user.name", "Deployment Test")
        self.git(self.origin, "config", "commit.gpgsign", "false")
        (self.origin / "VERSION").write_text("0.4.99\n")
        self.git(self.origin, "add", "VERSION")
        self.git(self.origin, "commit", "-m", "release")
        self.commit = self.git(self.origin, "rev-parse", "HEAD")
        self.git(self.origin, "tag", "v0.4.99")
        self.git(self.root, "clone", str(self.origin), str(self.checkout))
        self.git(self.checkout, "checkout", "--detach", self.commit)

    @staticmethod
    def git(root: Path, *args: str) -> str:
        return publish_play.git(root, *args)

    def test_detached_main_commit_can_deploy_to_both_environments(self) -> None:
        self.assertEqual(("0.4.99", self.commit), publish_play.validate_deployment(self.checkout, "staging"))
        with patch.object(publish_play, "fetch_text", return_value="0.4.99\n"):
            self.assertEqual(("0.4.99", "v0.4.99"), publish_play.validate_deployment(self.checkout, "production"))

    def test_queued_staging_commit_does_not_switch_to_new_main(self) -> None:
        self.git(self.origin, "commit", "--allow-empty", "-m", "next merge")
        self.assertEqual(("0.4.99", self.commit), publish_play.validate_deployment(self.checkout, "staging"))
        with self.assertRaisesRegex(ReleaseError, "must match origin/main"):
            publish_play.validate_deployment(self.checkout, "production")

    def test_staging_needs_no_release_tag_but_production_does(self) -> None:
        self.git(self.origin, "tag", "-d", "v0.4.99")
        self.git(self.checkout, "tag", "-d", "v0.4.99")
        self.assertEqual(("0.4.99", self.commit), publish_play.validate_deployment(self.checkout, "staging"))
        with self.assertRaises(ReleaseError):
            publish_play.validate_deployment(self.checkout, "production")

    def test_unmerged_commit_cannot_deploy(self) -> None:
        self.git(self.checkout, "-c", "user.name=Test", "-c", "user.email=test@example.test",
                 "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", "unmerged")
        for environment in ("staging", "production"):
            with self.subTest(environment=environment), self.assertRaises(ReleaseError):
                publish_play.validate_deployment(self.checkout, environment)

    def test_dirty_checkout_cannot_deploy(self) -> None:
        (self.checkout / "VERSION").write_text("0.4.100\n")
        with self.assertRaisesRegex(ReleaseError, "tracked files are dirty"):
            publish_play.validate_deployment(self.checkout, "staging")


if __name__ == "__main__":
    unittest.main()
