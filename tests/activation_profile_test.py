from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "play-profile"


class ActivationProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.roots = [base / "codex" / "skills", base / "claude" / "skills"]
        self.state = base / "state" / "profile.json"
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

        for skill in (self.roots[0] / "rote", self.roots[1] / "rote-shell"):
            self.assertIn(
                "disable-model-invocation: true", (skill / "SKILL.md").read_text()
            )
            self.assertIn(
                "allow_implicit_invocation: false",
                (skill / "agents" / "openai.yaml").read_text(),
            )

        self.run_profile("verify")
        result = self.run_profile("install")
        self.assertIn("already active", result.stdout)
        self.run_profile("uninstall")

        self.assertFalse(self.state.exists())
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


if __name__ == "__main__":
    unittest.main()
