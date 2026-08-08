from __future__ import annotations

import json
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "harness" / "play-profile"


class ActivationProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.roots = [base / "codex" / "skills", base / "claude" / "skills"]
        self.state = base / "state" / "profile.json"
        self.launcher = base / "bin" / "play-machine"
        self.originals: dict[Path, bytes] = {}

        for index, root in enumerate(self.roots):
            skill = root / ("rote" if index == 0 else "rote-shell")
            skill.mkdir(parents=True)
            markdown = (
                f"---\nname: {skill.name}\ndescription: test\n---\n\n# Test\n".encode()
            )
            (skill / "SKILL.md").write_bytes(markdown)
            self.originals[skill / "SKILL.md"] = markdown

        metadata = self.roots[0] / "rote" / "agents" / "openai.yaml"
        metadata.parent.mkdir()
        content = b'interface:\n  display_name: "Rote"\n'
        metadata.write_bytes(content)
        self.originals[metadata] = content

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_profile(
        self, command: str, expected: int = 0
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PLAY_HARNESS_ROOTS"] = os.pathsep.join(map(str, self.roots))
        environment["PLAY_PROFILE_STATE"] = str(self.state)
        environment["PLAY_MACHINE_LAUNCHER"] = str(self.launcher)
        if hasattr(self, "source"):
            environment["PLAY_PROFILE_SOURCE"] = str(self.source)
        result = subprocess.run(
            [str(SCRIPT), command],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
        )
        self.assertEqual(expected, result.returncode, result.stderr)
        return result

    def test_install_verify_idempotency_and_uninstall(self) -> None:
        self.run_profile("install")

        for root in self.roots:
            play = root / "play"
            self.assertTrue(play.is_symlink())
            self.assertEqual(ROOT, play.resolve())
        self.assertTrue(self.launcher.is_file())
        self.assertTrue(os.access(self.launcher, os.X_OK))

        for skill in (self.roots[0] / "rote", self.roots[1] / "rote-shell"):
            self.assertIn(
                "disable-model-invocation: false", (skill / "SKILL.md").read_text()
            )
            self.assertIn(
                "allow_implicit_invocation: true",
                (skill / "agents" / "openai.yaml").read_text(),
            )

        self.run_profile("verify")
        result = self.run_profile("install")
        self.assertIn("already active", result.stdout)
        self.run_profile("uninstall")

        self.assertFalse(self.state.exists())
        self.assertFalse(self.launcher.exists())
        for root in self.roots:
            self.assertFalse((root / "play").exists())
        for path, content in self.originals.items():
            self.assertEqual(content, path.read_bytes())
        self.assertFalse((self.roots[1] / "rote-shell" / "agents").exists())

    def test_existing_play_install_fails_without_mutating_rote(self) -> None:
        conflict = self.roots[0] / "play"
        conflict.mkdir()
        before = (self.roots[0] / "rote" / "SKILL.md").read_bytes()
        result = self.run_profile("install", expected=1)
        self.assertIn("refusing to replace", result.stderr)
        self.assertEqual(before, (self.roots[0] / "rote" / "SKILL.md").read_bytes())
        self.assertFalse(self.state.exists())

    def test_uninstall_refuses_to_overwrite_changed_activation_files(self) -> None:
        self.run_profile("install")
        markdown = self.roots[0] / "rote" / "SKILL.md"
        markdown.write_text(markdown.read_text() + "\nchanged after activation\n")

        result = self.run_profile("uninstall", expected=1)

        self.assertIn("changed since install", result.stderr)
        self.assertTrue((self.roots[0] / "play").is_symlink())
        self.assertTrue(self.state.exists())

    def test_install_rebases_refreshed_rote_skill_and_remains_reversible(self) -> None:
        self.run_profile("install")
        skill = self.roots[0] / "rote"
        markdown = skill / "SKILL.md"
        metadata = skill / "agents" / "openai.yaml"
        refreshed_markdown = b"---\nname: rote\ndescription: refreshed\n---\n\n# Refreshed\n"
        refreshed_metadata = b'interface:\n  display_name: "Refreshed Rote"\n'
        markdown.write_bytes(refreshed_markdown)
        metadata.write_bytes(refreshed_metadata)

        result = self.run_profile("install")

        self.assertIn("reconciled", result.stdout)
        self.assertIn("disable-model-invocation: false", markdown.read_text())
        self.assertIn("allow_implicit_invocation: true", metadata.read_text())
        self.run_profile("uninstall")
        self.assertEqual(refreshed_markdown, markdown.read_bytes())
        self.assertEqual(refreshed_metadata, metadata.read_bytes())

    def test_install_converges_a_new_harness_root(self) -> None:
        self.run_profile("install")
        new_root = Path(self.temporary.name) / "new-harness" / "skills"
        new_skill = new_root / "rote-new"
        new_skill.mkdir(parents=True)
        original = b"---\nname: rote-new\ndescription: new\n---\n"
        (new_skill / "SKILL.md").write_bytes(original)
        self.roots.append(new_root)

        result = self.run_profile("install")

        self.assertIn("reconciled", result.stdout)
        self.assertTrue((new_root / "play").is_symlink())
        self.assertIn(
            "disable-model-invocation: false", (new_skill / "SKILL.md").read_text()
        )
        self.run_profile("uninstall")
        self.assertEqual(original, (new_skill / "SKILL.md").read_bytes())

    def test_install_migrates_legacy_explicit_only_profile_without_losing_backups(self) -> None:
        self.run_profile("install")
        state = json.loads(self.state.read_text())
        state.pop("activation_policy")
        for value in state["rote_skills"]:
            skill = Path(value)
            markdown = skill / "SKILL.md"
            metadata = skill / "agents" / "openai.yaml"
            markdown.write_text(
                markdown.read_text().replace(
                    "disable-model-invocation: false",
                    "disable-model-invocation: true",
                )
            )
            metadata.write_text(
                metadata.read_text().replace(
                    "allow_implicit_invocation: true",
                    "allow_implicit_invocation: false",
                )
            )
            for path in (markdown, metadata):
                state["backups"][str(path)]["managed_sha256"] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
        self.state.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

        result = self.run_profile("install")

        self.assertIn("reconciled", result.stdout)
        migrated = json.loads(self.state.read_text())
        self.assertEqual("rote-handoff-invocable/v1", migrated["activation_policy"])
        for value in migrated["rote_skills"]:
            skill = Path(value)
            self.assertIn(
                "disable-model-invocation: false", (skill / "SKILL.md").read_text()
            )
            self.assertIn(
                "allow_implicit_invocation: true",
                (skill / "agents" / "openai.yaml").read_text(),
            )

        self.run_profile("uninstall")
        for path, content in self.originals.items():
            self.assertEqual(content, path.read_bytes())

    def test_marketplace_install_does_not_create_duplicate_play_links(self) -> None:
        plugin = Path(self.temporary.name) / "plugin"
        self.source = plugin / "skills" / "play"
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".codex-plugin" / "plugin.json").write_text("{}\n")
        (self.source / "agents").mkdir(parents=True)
        (self.source / "SKILL.md").write_bytes((ROOT / "SKILL.md").read_bytes())
        (self.source / "agents" / "openai.yaml").write_bytes(
            (ROOT / "agents" / "openai.yaml").read_bytes()
        )

        result = self.run_profile("install")

        self.assertIn("marketplace", result.stdout)
        for root in self.roots:
            self.assertFalse((root / "play").exists())
        state = json.loads(self.state.read_text())
        self.assertEqual("marketplace", state["mode"])
        self.assertEqual([], state["play_links"])
        self.run_profile("verify")
        self.run_profile("uninstall")


if __name__ == "__main__":
    unittest.main()
