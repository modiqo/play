from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TAG = "v1.2.3"


class ReleaseTaggingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkout = self.root / "play"
        self.remote = self.root / "origin.git"
        self.output = self.root / "github-output"
        self.checkout.mkdir()
        self.env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Release test",
            "GIT_AUTHOR_EMAIL": "release@example.invalid",
            "GIT_COMMITTER_NAME": "Release test",
            "GIT_COMMITTER_EMAIL": "release@example.invalid",
        }
        self.git("init", "--bare", "--initial-branch=main", str(self.remote))
        self.git("init", "--initial-branch=main")
        self.git("remote", "add", "origin", str(self.remote))
        (self.checkout / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        self.git("add", "VERSION")
        self.git("commit", "-m", "Initial release")
        self.commit = self.git("rev-parse", "HEAD")
        self.git("push", "origin", "main")
        release = self.checkout / ".github/release"
        release.mkdir(parents=True)
        for name in ("tag_play.py", "publish_play.py"):
            shutil.copyfile(ROOT / ".github/release" / name, release / name)

    def git(self, *arguments: str, remote: bool = False) -> str:
        return subprocess.run(
            ("git", *arguments),
            cwd=self.remote if remote else self.checkout,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def invoke(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (
                sys.executable, ".github/release/tag_play.py",
                "--commit", self.commit, "--github-output", str(self.output),
                *arguments,
            ),
            cwd=self.checkout,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def receipt(self, *arguments: str) -> dict[str, object]:
        result = self.invoke(*arguments)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def publish_fixture_tag(self, *, annotated: bool = True) -> str:
        if annotated:
            self.git("tag", "--annotate", TAG, "--message", "Existing release")
        else:
            self.git("tag", TAG)
        self.git("push", "origin", f"refs/tags/{TAG}")
        tag_object = self.git("rev-parse", f"refs/tags/{TAG}", remote=True)
        self.git("tag", "--delete", TAG)
        return tag_object

    def test_new_version_check_is_read_only_and_publish_is_idempotent(self) -> None:
        self.output.write_text("unrelated=preserved\n", encoding="utf-8")
        self.assertEqual("ready", self.receipt("--dry-run")["status"])
        self.assertEqual("unrelated=preserved\nstatus=ready\n", self.output.read_text())
        self.assertEqual("", self.git("tag", "--list"))
        self.assertEqual("", self.git("tag", "--list", remote=True))

        self.assertEqual("tagged", self.receipt()["status"])
        tag_object = self.git("rev-parse", f"refs/tags/{TAG}", remote=True)
        self.assertEqual(self.commit, self.git("rev-parse", f"{TAG}^{{commit}}", remote=True))
        self.assertEqual("already_tagged", self.receipt()["status"])
        self.assertEqual(tag_object, self.git("rev-parse", f"refs/tags/{TAG}", remote=True))
        self.assertTrue(self.output.read_text().endswith("status=already_tagged\n"))

    def test_existing_version_on_earlier_commit_does_not_create_or_move_tag(self) -> None:
        tag_object = self.publish_fixture_tag()
        tagged_commit = self.commit
        self.git("commit", "--allow-empty", "-m", "Change without a version bump")
        self.commit = self.git("rev-parse", "HEAD")
        self.git("push", "origin", "main")

        checked = self.receipt("--dry-run")
        self.assertEqual("version_unchanged", checked["status"])
        self.assertEqual(tagged_commit, checked["tagged_commit"])
        self.assertEqual("status=version_unchanged\n", self.output.read_text())
        self.assertEqual("version_unchanged", self.receipt()["status"])
        self.assertEqual("", self.git("tag", "--list"))
        self.assertEqual(tag_object, self.git("rev-parse", f"refs/tags/{TAG}", remote=True))

    def test_existing_lightweight_tag_at_commit_does_not_create_a_local_tag(self) -> None:
        tag_object = self.publish_fixture_tag(annotated=False)
        self.assertEqual("already_tagged", self.receipt("--dry-run")["status"])
        self.assertEqual("status=already_tagged\n", self.output.read_text())
        self.assertEqual("already_tagged", self.receipt()["status"])
        self.assertEqual("", self.git("tag", "--list"))
        self.assertEqual(tag_object, self.git("rev-parse", f"refs/tags/{TAG}", remote=True))

    def test_tag_created_after_check_is_preserved(self) -> None:
        self.assertEqual("ready", self.receipt("--dry-run")["status"])
        tag_object = self.publish_fixture_tag()
        self.assertEqual("already_tagged", self.receipt()["status"])
        self.assertEqual("", self.git("tag", "--list"))
        self.assertEqual(tag_object, self.git("rev-parse", f"refs/tags/{TAG}", remote=True))

    def test_conflicting_tag_fails_without_enabling_creation(self) -> None:
        self.git("commit", "--allow-empty", "-m", "Later commit")
        self.git("push", "origin", "main")
        tag_object = self.publish_fixture_tag()
        result = self.invoke("--dry-run")
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("refusing to move it", result.stderr)
        self.assertFalse(self.output.exists())
        self.assertEqual(tag_object, self.git("rev-parse", f"refs/tags/{TAG}", remote=True))

    def test_remote_lookup_failure_does_not_enable_creation(self) -> None:
        self.git("remote", "set-url", "--push", "origin", str(self.root / "missing.git"))
        result = self.invoke("--dry-run")
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("could not read from remote repository", result.stderr.lower())
        self.assertFalse(self.output.exists())
        self.assertEqual("", self.git("tag", "--list", remote=True))


if __name__ == "__main__":
    unittest.main()
