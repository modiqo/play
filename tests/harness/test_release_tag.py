from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.release import tag_play
from scripts.release.publish_play import ReleaseError, git


class ReleaseTagTest(unittest.TestCase):
    """Use local Git repositories to test real tag creation and push behavior."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.origin = self.root / "origin.git"
        self.seed = self.root / "seed"
        self.checkout = self.root / "checkout"
        git(self.root, "init", "--bare", "--initial-branch=main", str(self.origin))
        git(self.root, "init", "--initial-branch=main", str(self.seed))
        self.configure(self.seed)
        self.commit = self.add_commit(self.seed, "0.5.0")
        git(self.seed, "remote", "add", "origin", str(self.origin))
        git(self.seed, "push", "origin", "main")
        git(self.root, "clone", str(self.origin), str(self.checkout))
        self.configure(self.checkout)
        git(self.checkout, "checkout", "-b", "work")

    @staticmethod
    def configure(repository: Path) -> None:
        for name, value in (
            ("user.name", "Release Test"),
            ("user.email", "release@example.test"),
            ("commit.gpgsign", "false"),
            ("tag.gpgsign", "false"),
            ("push.followTags", "false"),
        ):
            git(repository, "config", name, value)

    @staticmethod
    def add_commit(repository: Path, version: str) -> str:
        (repository / "VERSION").write_text(version + "\n")
        git(repository, "add", "VERSION")
        git(repository, "commit", "--allow-empty", "-m", f"Version {version}")
        return git(repository, "rev-parse", "HEAD")

    def remote_refs(self, repository: Path | None = None) -> str:
        return git(repository or self.origin, "for-each-ref", "--format=%(refname) %(objectname)")

    def test_default_fetches_main_and_reads_its_version_without_changing_checkout(self) -> None:
        merged = self.add_commit(self.seed, "1.0.0")
        git(self.seed, "push", "origin", "main")
        (self.checkout / "VERSION").write_text("99.9.9\n")
        result = tag_play.tag_release(self.checkout)
        self.assertEqual("tagged", result["status"])
        self.assertEqual("v1.0.0", result["tag"])
        self.assertEqual(merged, result["commit"])
        self.assertEqual(merged, git(self.origin, "rev-parse", "v1.0.0^{commit}"))
        self.assertEqual("tag", git(self.origin, "cat-file", "-t", "refs/tags/v1.0.0"))
        self.assertEqual("work", git(self.checkout, "branch", "--show-current"))
        self.assertEqual(self.commit, git(self.checkout, "rev-parse", "HEAD"))
        self.assertEqual("99.9.9\n", (self.checkout / "VERSION").read_text())

    def test_explicit_merged_commit_uses_its_own_version(self) -> None:
        latest = self.add_commit(self.seed, "0.6.0")
        git(self.seed, "push", "origin", "main")
        result = tag_play.tag_release(self.checkout, revision=self.commit)
        self.assertEqual("v0.5.0", result["tag"])
        self.assertEqual(self.commit, git(self.origin, "rev-parse", "v0.5.0^{commit}"))
        self.assertEqual(latest, git(self.origin, "rev-parse", "refs/heads/main"))

    def test_dry_run_does_not_create_or_push_tags(self) -> None:
        before = self.remote_refs()
        result = tag_play.tag_release(self.checkout, dry_run=True)
        self.assertEqual("ready", result["status"])
        self.assertTrue(result["dry_run"])
        self.assertEqual("v0.5.0", result["tag"])
        self.assertEqual("", git(self.checkout, "tag", "--list"))
        self.assertEqual(before, self.remote_refs())

    def test_repeat_is_a_noop_even_with_annotated_tag(self) -> None:
        tag_play.tag_release(self.checkout)
        before = self.remote_refs()
        result = tag_play.tag_release(self.checkout)
        self.assertEqual("already_tagged", result["status"])
        self.assertEqual(before, self.remote_refs())

    def test_existing_remote_lightweight_tag_is_a_noop_without_local_tag(self) -> None:
        git(self.seed, "tag", "v0.5.0", self.commit)
        git(self.seed, "push", "origin", "refs/tags/v0.5.0")
        result = tag_play.tag_release(self.checkout)
        self.assertEqual("already_tagged", result["status"])
        self.assertEqual("", git(self.checkout, "tag", "--list"))

    def test_existing_matching_local_tag_can_be_pushed(self) -> None:
        git(self.checkout, "tag", "v0.5.0", self.commit)
        result = tag_play.tag_release(self.checkout)
        self.assertEqual("tagged", result["status"])
        self.assertEqual(self.commit, git(self.origin, "rev-parse", "v0.5.0^{commit}"))

    def test_unmerged_commit_is_rejected_without_tagging(self) -> None:
        feature = self.add_commit(self.checkout, "0.6.0")
        before = self.remote_refs()
        with self.assertRaisesRegex(ReleaseError, "must already belong to origin/main"):
            tag_play.tag_release(self.checkout, revision=feature)
        self.assertEqual(before, self.remote_refs())
        self.assertEqual("", git(self.checkout, "tag", "--list"))

    def test_invalid_committed_version_is_rejected(self) -> None:
        self.add_commit(self.seed, "0.5")
        git(self.seed, "push", "origin", "main")
        before = self.remote_refs()
        with self.assertRaisesRegex(ReleaseError, "VERSION must be semantic"):
            tag_play.tag_release(self.checkout)
        self.assertEqual(before, self.remote_refs())
        self.assertEqual("", git(self.checkout, "tag", "--list"))

    def test_conflicting_local_tag_is_never_moved_or_pushed(self) -> None:
        feature = self.add_commit(self.checkout, "0.6.0")
        git(self.checkout, "tag", "v0.5.0", feature)
        before = self.remote_refs()
        with self.assertRaisesRegex(ReleaseError, "local v0.5.0 points to"):
            tag_play.tag_release(self.checkout)
        self.assertEqual(feature, git(self.checkout, "rev-parse", "v0.5.0^{commit}"))
        self.assertEqual(before, self.remote_refs())

    def test_conflicting_remote_tag_is_never_moved_and_no_local_tag_is_created(self) -> None:
        newer = self.add_commit(self.seed, "0.6.0")
        git(self.seed, "tag", "--annotate", "v0.5.0", newer, "--message", "Wrong release")
        git(self.seed, "push", "origin", "main", "refs/tags/v0.5.0")
        before = self.remote_refs()
        with self.assertRaisesRegex(ReleaseError, "remote v0.5.0 points to"):
            tag_play.tag_release(self.checkout, revision=self.commit)
        self.assertEqual(before, self.remote_refs())
        self.assertEqual("", git(self.checkout, "tag", "--list"))

    def test_push_ignores_follow_tags_and_default_branch_refspec(self) -> None:
        git(self.checkout, "tag", "--annotate", "unrelated", self.commit, "--message", "Other tag")
        self.add_commit(self.checkout, "9.0.0")
        git(self.checkout, "config", "push.followTags", "true")
        git(self.checkout, "config", "remote.origin.push", "refs/heads/work:refs/heads/main")
        tag_play.tag_release(self.checkout)
        self.assertEqual(self.commit, git(self.origin, "rev-parse", "refs/heads/main"))
        self.assertEqual("v0.5.0", git(self.origin, "tag", "--list"))
        self.assertEqual("refs/heads/main", git(self.origin, "for-each-ref", "--format=%(refname)", "refs/heads"))

    def test_failed_push_preserves_tag_for_retry_and_reports_failure(self) -> None:
        hook = self.origin / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        before = self.remote_refs()
        with self.assertRaisesRegex(ReleaseError, "hook declined"):
            tag_play.tag_release(self.checkout)
        self.assertEqual(before, self.remote_refs())
        self.assertEqual(self.commit, git(self.checkout, "rev-parse", "v0.5.0^{commit}"))
        hook.unlink()
        self.assertEqual("tagged", tag_play.tag_release(self.checkout)["status"])

    def test_remote_conflict_created_during_push_is_not_overwritten(self) -> None:
        newer = self.add_commit(self.seed, "0.6.0")
        git(self.seed, "push", "origin", "main")
        # Simulate a competing publisher after the remote preflight, before this push.
        hook = self.checkout / ".git/hooks/pre-push"
        hook.write_text(f'#!/bin/sh\ngit --git-dir="{self.origin}" update-ref refs/tags/v0.5.0 {newer}\n')
        hook.chmod(0o755)
        with self.assertRaises(ReleaseError):
            tag_play.tag_release(self.checkout, revision=self.commit)
        self.assertEqual(newer, git(self.origin, "rev-parse", "v0.5.0^{commit}"))

    def test_checks_the_actual_push_destination_for_conflicts(self) -> None:
        destination = self.root / "other.git"
        git(self.root, "clone", "--bare", str(self.origin), str(destination))
        newer = self.add_commit(self.seed, "0.6.0")
        git(self.seed, "push", str(destination), f"{newer}:refs/tags/v0.5.0")
        git(self.checkout, "config", "remote.origin.pushurl", str(destination))
        before = self.remote_refs(destination)
        with self.assertRaisesRegex(ReleaseError, "remote v0.5.0 points to"):
            tag_play.tag_release(self.checkout)
        self.assertEqual(before, self.remote_refs(destination))
        self.assertEqual("", git(self.checkout, "tag", "--list"))

    def test_refuses_multiple_push_destinations(self) -> None:
        git(self.checkout, "config", "--add", "remote.origin.pushurl", str(self.origin))
        git(self.checkout, "config", "--add", "remote.origin.pushurl", str(self.root / "other.git"))
        with self.assertRaisesRegex(ReleaseError, "exactly one push URL"):
            tag_play.tag_release(self.checkout)
        self.assertEqual("", git(self.checkout, "tag", "--list"))

    @unittest.skipUnless(shutil.which("just"), "just is required for the recipe integration test")
    def test_just_targets_use_the_helper_with_optional_commit(self) -> None:
        # Run the real Just/CLI path in a clone whose origin is a local fixture.
        helpers = self.checkout / "scripts/release"
        helpers.mkdir(parents=True)
        for name in ("tag_play.py", "publish_play.py"):
            shutil.copy2(tag_play.ROOT / "scripts/release" / name, helpers / name)
        justfile = self.checkout / "justfile"
        shutil.copy2(tag_play.ROOT / "justfile", justfile)
        for target, expected_status, arguments in (
            ("release-tag-check", "ready", []),
            ("release-tag", "tagged", [self.commit]),
        ):
            with self.subTest(target=target):
                result = subprocess.run(
                    ["just", "--justfile", str(justfile), target, *arguments],
                    cwd=self.checkout, check=True, capture_output=True, text=True,
                )
                self.assertEqual(expected_status, json.loads(result.stdout)["status"])


if __name__ == "__main__":
    unittest.main()
