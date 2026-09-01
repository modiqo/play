from __future__ import annotations

import json
import hashlib
import os
import shutil
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
        self.routing_launcher = base / "bin" / "play-routing"
        self.journey_launcher = base / "bin" / "play-journey"
        self.cli_launcher = base / "bin" / "play"
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
        self,
        command: str,
        expected: int = 0,
        *,
        roots: list[Path] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PLAY_HARNESS_ROOTS"] = os.pathsep.join(
            map(str, self.roots if roots is None else roots)
        )
        environment["PLAY_PROFILE_STATE"] = str(self.state)
        environment["PLAY_MACHINE_LAUNCHER"] = str(self.launcher)
        environment["PLAY_ROUTING_LAUNCHER"] = str(self.routing_launcher)
        environment["PLAY_JOURNEY_LAUNCHER"] = str(self.journey_launcher)
        environment["PLAY_CLI_LAUNCHER"] = str(self.cli_launcher)
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
        self.assertTrue(self.routing_launcher.is_file())
        self.assertTrue(os.access(self.routing_launcher, os.X_OK))
        self.assertTrue(self.journey_launcher.is_file())
        self.assertTrue(os.access(self.journey_launcher, os.X_OK))
        self.assertTrue(self.cli_launcher.is_file())
        self.assertTrue(os.access(self.cli_launcher, os.X_OK))
        self.assertIn(str(ROOT / "scripts/bin/play"), self.cli_launcher.read_text())

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
        self.assertFalse(self.routing_launcher.exists())
        self.assertFalse(self.journey_launcher.exists())
        self.assertFalse(self.cli_launcher.exists())
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

    def test_upgrade_adds_cli_launcher_to_legacy_profile_state(self) -> None:
        self.run_profile("install")
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state.pop("cli_launcher")
        state["backups"].pop(str(self.cli_launcher.resolve()), None)
        self.state.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.cli_launcher.unlink()

        self.run_profile("install")

        upgraded = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(str(self.cli_launcher.resolve()), upgraded["cli_launcher"])
        self.assertTrue(self.cli_launcher.is_file())
        self.assertIn(str(self.cli_launcher.resolve()), upgraded["backups"])

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

    def test_reconcile_restores_managed_play_links_removed_by_skill_refresh(self) -> None:
        self.run_profile("install")
        for root in self.roots:
            (root / "play").unlink()

        result = self.run_profile("install")

        self.assertIn("restored 2 managed Play link(s)", result.stdout)
        for root in self.roots:
            play = root / "play"
            self.assertTrue(play.is_symlink())
            self.assertEqual(ROOT, play.resolve())
        self.run_profile("verify")

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

    def test_subset_reinstall_preserves_previously_managed_harness_links(self) -> None:
        self.run_profile("install")

        result = self.run_profile("install", roots=[self.roots[0]])

        self.assertIn("already active across 2 harness root(s)", result.stdout)
        for root in self.roots:
            self.assertTrue((root / "play").is_symlink())
            self.assertEqual(ROOT, (root / "play").resolve())
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(str(root.resolve()) for root in self.roots),
            sorted(state["roots"]),
        )
        self.run_profile("verify", roots=[self.roots[0]])

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

    def test_marketplace_install_creates_launcher_before_rote_skills_exist(self) -> None:
        plugin = Path(self.temporary.name) / "plugin-empty"
        self.source = plugin / "skills" / "play"
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".codex-plugin" / "plugin.json").write_text("{}\n")
        (self.source / "agents").mkdir(parents=True)
        (self.source / "SKILL.md").write_bytes((ROOT / "SKILL.md").read_bytes())
        (self.source / "agents" / "openai.yaml").write_bytes(
            (ROOT / "agents" / "openai.yaml").read_bytes()
        )
        empty_root = Path(self.temporary.name) / "empty" / "skills"
        empty_root.mkdir(parents=True)
        self.roots = [empty_root]

        result = self.run_profile("install")

        self.assertIn("0 harness root(s)", result.stdout)
        self.assertTrue(self.launcher.is_file())
        self.assertIn(str(self.source / "scripts/bin/play-machine"), self.launcher.read_text())
        self.assertTrue(self.routing_launcher.is_file())
        self.assertIn(
            str(self.source / "scripts/bin/play-routing"),
            self.routing_launcher.read_text(),
        )
        state = json.loads(self.state.read_text())
        self.assertEqual([], state["roots"])
        self.assertEqual([], state["rote_skills"])

    def test_marketplace_upgrade_retargets_managed_launcher(self) -> None:
        plugin_v1 = Path(self.temporary.name) / "plugin-v1"
        plugin_v2 = Path(self.temporary.name) / "plugin-v2"
        for plugin in (plugin_v1, plugin_v2):
            source = plugin / "skills" / "play"
            (plugin / ".codex-plugin").mkdir(parents=True)
            (plugin / ".codex-plugin" / "plugin.json").write_text("{}\n")
            (source / "agents").mkdir(parents=True)
            (source / "SKILL.md").write_bytes((ROOT / "SKILL.md").read_bytes())
            (source / "agents" / "openai.yaml").write_bytes(
                (ROOT / "agents" / "openai.yaml").read_bytes()
            )

        self.source = plugin_v1 / "skills" / "play"
        self.run_profile("install")
        self.assertIn(str(self.source), self.launcher.read_text())

        self.source = plugin_v2 / "skills" / "play"
        result = self.run_profile("install")

        self.assertIn("reconciled", result.stdout)
        self.assertIn(str(self.source), self.launcher.read_text())
        state = json.loads(self.state.read_text())
        self.assertEqual(str(self.source.resolve()), state["source"])

    def test_marketplace_activation_repairs_a_missing_portable_source(self) -> None:
        portable = Path(self.temporary.name) / "portable" / "skill"
        (portable / "agents").mkdir(parents=True)
        (portable / "scripts" / "bin").mkdir(parents=True)
        (portable / "SKILL.md").write_bytes((ROOT / "SKILL.md").read_bytes())
        (portable / "agents" / "openai.yaml").write_bytes(
            (ROOT / "agents" / "openai.yaml").read_bytes()
        )
        (portable / "scripts" / "bin" / "play-machine").write_text("#!/bin/sh\n")
        self.source = portable
        self.run_profile("install")
        self.assertIn(str(portable / "scripts/bin/play-machine"), self.launcher.read_text())

        shutil.rmtree(portable)
        plugin = Path(self.temporary.name) / "plugin-repair"
        repaired_source = plugin / "skills" / "play"
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".codex-plugin" / "plugin.json").write_text("{}\n")
        (repaired_source / "agents").mkdir(parents=True)
        (repaired_source / "SKILL.md").write_bytes((ROOT / "SKILL.md").read_bytes())
        (repaired_source / "agents" / "openai.yaml").write_bytes(
            (ROOT / "agents" / "openai.yaml").read_bytes()
        )
        self.source = repaired_source

        result = self.run_profile("install")

        self.assertIn("restored activation from missing Play source", result.stdout)
        self.assertIn(
            str(repaired_source / "scripts/bin/play-machine"), self.launcher.read_text()
        )
        state = json.loads(self.state.read_text())
        self.assertEqual("marketplace", state["mode"])
        self.assertEqual(str(repaired_source.resolve()), state["source"])
        for root in self.roots:
            self.assertFalse((root / "play").exists())

    def test_activation_does_not_take_over_an_available_different_source(self) -> None:
        first = Path(self.temporary.name) / "first" / "skill"
        second = Path(self.temporary.name) / "second" / "skill"
        for source in (first, second):
            (source / "agents").mkdir(parents=True)
            (source / "scripts" / "bin").mkdir(parents=True)
            (source / "SKILL.md").write_bytes((ROOT / "SKILL.md").read_bytes())
            (source / "agents" / "openai.yaml").write_bytes(
                (ROOT / "agents" / "openai.yaml").read_bytes()
            )
            (source / "scripts" / "bin" / "play-machine").write_text("#!/bin/sh\n")
        self.source = first
        self.run_profile("install")
        self.source = second

        result = self.run_profile("install", expected=1)

        self.assertIn("profile state belongs to another Play source", result.stderr)
        self.assertIn(str(first / "scripts/bin/play-machine"), self.launcher.read_text())

    def test_portable_install_backs_up_and_migrates_available_source(self) -> None:
        checkout = Path(self.temporary.name) / "checkout" / "skill"
        portable = Path(self.temporary.name) / "portable" / "skill"
        for source in (checkout, portable):
            (source / "agents").mkdir(parents=True)
            (source / "scripts" / "bin").mkdir(parents=True)
            (source / "SKILL.md").write_bytes((ROOT / "SKILL.md").read_bytes())
            (source / "agents" / "openai.yaml").write_bytes(
                (ROOT / "agents" / "openai.yaml").read_bytes()
            )
            (source / "scripts" / "bin" / "play-machine").write_text("#!/bin/sh\n")
        (portable / ".play-install.json").write_text(
            json.dumps(
                {
                    "schema": "play.portable-install/v1",
                    "source": "portable-copy",
                    "version": "test",
                }
            )
            + "\n"
        )

        self.source = checkout
        self.run_profile("install")
        previous_state = self.state.read_bytes()

        skill = self.roots[0] / "rote"
        markdown = skill / "SKILL.md"
        metadata = skill / "agents" / "openai.yaml"
        refreshed_markdown = b"---\nname: rote\ndescription: refreshed\n---\n\n# Refreshed\n"
        refreshed_metadata = b'interface:\n  display_name: "Refreshed Rote"\n'
        markdown.write_bytes(refreshed_markdown)
        metadata.write_bytes(refreshed_metadata)

        self.source = portable
        result = self.run_profile("install")

        self.assertIn("backed up previous activation profile", result.stdout)
        migrated = json.loads(self.state.read_text())
        self.assertEqual(str(portable.resolve()), migrated["source"])
        self.assertEqual(1, len(migrated["profile_backups"]))
        backup = Path(migrated["profile_backups"][0]["path"])
        self.assertEqual(previous_state, backup.read_bytes())
        self.assertEqual(0o600, backup.stat().st_mode & 0o777)
        self.assertEqual(0o700, backup.parent.stat().st_mode & 0o777)
        for root in self.roots:
            self.assertEqual(portable.resolve(), (root / "play").resolve())
        self.assertIn(str(portable / "scripts/bin/play-machine"), self.launcher.read_text())

        self.run_profile("uninstall")
        self.assertEqual(refreshed_markdown, markdown.read_bytes())
        self.assertEqual(refreshed_metadata, metadata.read_bytes())
        self.assertTrue(backup.is_file())

    def test_checkout_install_backs_up_and_migrates_available_portable_source(self) -> None:
        checkout = Path(self.temporary.name) / "checkout-return" / "skill"
        portable = Path(self.temporary.name) / "portable-current" / "skill"
        for source in (checkout, portable):
            (source / "agents").mkdir(parents=True)
            (source / "scripts" / "bin").mkdir(parents=True)
            (source / "SKILL.md").write_bytes((ROOT / "SKILL.md").read_bytes())
            (source / "agents" / "openai.yaml").write_bytes(
                (ROOT / "agents" / "openai.yaml").read_bytes()
            )
            (source / "scripts" / "bin" / "play-machine").write_text("#!/bin/sh\n")
        (portable / ".play-install.json").write_text(
            json.dumps(
                {
                    "schema": "play.portable-install/v1",
                    "source": "portable-copy",
                    "version": "test",
                }
            )
            + "\n"
        )

        self.source = portable
        self.run_profile("install")
        previous_state = self.state.read_bytes()

        self.source = checkout
        result = self.run_profile("install")

        self.assertIn("backed up previous activation profile", result.stdout)
        migrated = json.loads(self.state.read_text())
        self.assertEqual(str(checkout.resolve()), migrated["source"])
        backup = Path(migrated["profile_backups"][0]["path"])
        self.assertEqual(previous_state, backup.read_bytes())
        for root in self.roots:
            self.assertEqual(checkout.resolve(), (root / "play").resolve())
        self.assertIn(str(checkout / "scripts/bin/play-machine"), self.launcher.read_text())

        self.run_profile("uninstall")
        self.assertTrue(backup.is_file())

    def test_portable_install_takes_over_available_marketplace_profile(self) -> None:
        plugin = Path(self.temporary.name) / "plugin-current"
        plugin_source = plugin / "skills" / "play"
        portable = Path(self.temporary.name) / "portable-current" / "skill"
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".codex-plugin" / "plugin.json").write_text("{}\n")
        for source in (plugin_source, portable):
            (source / "agents").mkdir(parents=True)
            (source / "scripts" / "bin").mkdir(parents=True)
            (source / "SKILL.md").write_bytes((ROOT / "SKILL.md").read_bytes())
            (source / "agents" / "openai.yaml").write_bytes(
                (ROOT / "agents" / "openai.yaml").read_bytes()
            )
            (source / "scripts" / "bin" / "play-machine").write_text("#!/bin/sh\n")
        (portable / ".play-install.json").write_text(
            json.dumps(
                {
                    "schema": "play.portable-install/v1",
                    "source": "portable-copy",
                    "version": "test",
                }
            )
            + "\n"
        )

        self.source = plugin_source
        self.run_profile("install")
        previous_state = self.state.read_bytes()
        self.source = portable

        result = self.run_profile("install")

        self.assertIn("backed up previous activation profile", result.stdout)
        state = json.loads(self.state.read_text())
        self.assertEqual("source-linked", state["mode"])
        self.assertEqual(str(portable.resolve()), state["source"])
        self.assertEqual(previous_state, Path(state["profile_backups"][0]["path"]).read_bytes())
        for root in self.roots:
            self.assertEqual(portable.resolve(), (root / "play").resolve())

    def test_portable_migration_fails_closed_when_backup_path_is_unsafe(self) -> None:
        checkout = Path(self.temporary.name) / "checkout-unsafe" / "skill"
        portable = Path(self.temporary.name) / "portable-unsafe" / "skill"
        for source in (checkout, portable):
            (source / "agents").mkdir(parents=True)
            (source / "scripts" / "bin").mkdir(parents=True)
            (source / "SKILL.md").write_bytes((ROOT / "SKILL.md").read_bytes())
            (source / "agents" / "openai.yaml").write_bytes(
                (ROOT / "agents" / "openai.yaml").read_bytes()
            )
            (source / "scripts" / "bin" / "play-machine").write_text("#!/bin/sh\n")
        (portable / ".play-install.json").write_text(
            json.dumps(
                {
                    "schema": "play.portable-install/v1",
                    "source": "portable-copy",
                    "version": "test",
                }
            )
            + "\n"
        )

        self.source = checkout
        self.run_profile("install")
        previous_state = self.state.read_bytes()
        (self.state.parent / "profile-backups").write_text("unsafe\n")

        self.source = portable
        result = self.run_profile("install", expected=1)

        self.assertIn("refusing unsafe profile backup path", result.stderr)
        self.assertEqual(previous_state, self.state.read_bytes())
        for root in self.roots:
            self.assertEqual(checkout.resolve(), (root / "play").resolve())
        self.assertIn(str(checkout / "scripts/bin/play-machine"), self.launcher.read_text())


if __name__ == "__main__":
    unittest.main()
