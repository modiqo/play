from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "harness" / "install-all"
PROFILE = ROOT / "scripts" / "harness" / "play-profile"


class InstallAllTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.roots = {
            "codex": self.home / ".codex" / "skills",
            "claude": self.home / ".claude" / "skills",
            "kimi": self.home / ".agents" / "skills",
        }
        for name, root in self.roots.items():
            skill = root / ("rote" if name != "claude" else "rote-shell")
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: {skill.name}\ndescription: test\n---\n",
                encoding="utf-8",
            )
            command = self.bin / name
            command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            command.chmod(0o755)

        self.state = self.home / "state" / "activation.json"
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "HOME": str(self.home),
                "PATH": os.pathsep.join(
                    (str(self.bin), str(Path(sys.executable).parent), "/usr/bin", "/bin")
                ),
                "CODEX_HOME": str(self.home / ".codex"),
                "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                "KIMI_CONFIG_DIR": str(self.home / ".kimi"),
                "AGENTS_HOME": str(self.home / ".agents"),
                "PLAY_HARNESS_ROOTS": os.pathsep.join(
                    str(path) for path in self.roots.values()
                ),
                "PLAY_PROFILE_STATE": str(self.state),
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_installer(
        self, *arguments: str, expected: int = 0
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [str(INSTALLER), *arguments],
            cwd=ROOT,
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(expected, result.returncode, result.stderr)
        return result

    def uninstall(self, source: Path) -> None:
        environment = {**self.environment, "PLAY_PROFILE_SOURCE": str(source)}
        subprocess.run(
            [str(source / "scripts" / "harness" / "play-profile"), "uninstall"],
            cwd=source,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_source_install_detects_and_verifies_every_harness(self) -> None:
        result = self.run_installer("install")

        self.assertIn("Detected harnesses: codex, claude, kimi", result.stdout)
        for name, root in self.roots.items():
            play = root / "play"
            self.assertTrue(play.is_symlink(), name)
            self.assertEqual(ROOT, play.resolve())

        launcher = self.home / ".local" / "bin" / "play-machine"
        self.assertTrue(launcher.is_file())
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertIn(str(ROOT / "scripts" / "bin" / "play-machine"), launcher.read_text())

        self.run_installer("verify")
        self.uninstall(ROOT)
        self.assertFalse(launcher.exists())

    def test_portable_copy_is_stable_and_idempotent(self) -> None:
        install_home = self.home / "portable"
        self.environment["PLAY_INSTALL_HOME"] = str(install_home)

        self.run_installer("install", "--copy")
        installed = install_home / "skill"
        self.assertEqual("0.3.0", (installed / "VERSION").read_text().strip())
        marker = json.loads((installed / ".play-install.json").read_text())
        self.assertEqual("play.portable-install/v1", marker["schema"])
        for root in self.roots.values():
            self.assertEqual(installed.resolve(), (root / "play").resolve())

        result = self.run_installer("install", "--copy")
        self.assertIn("already active", result.stdout)
        self.uninstall(installed)

    def test_missing_rote_provider_fails_before_writing(self) -> None:
        missing = self.roots["claude"] / "rote-shell"
        (missing / "SKILL.md").unlink()

        result = self.run_installer("install", expected=1)

        self.assertIn("Rote skill provider is missing", result.stderr)
        self.assertFalse(self.state.exists())
        for root in self.roots.values():
            self.assertFalse((root / "play").exists())

    def test_local_bootstrap_exercises_portable_install(self) -> None:
        install_home = self.home / "curl-portable"
        environment = {
            **self.environment,
            "PLAY_INSTALL_HOME": str(install_home),
            "PLAY_INSTALL_SOURCE": str(ROOT),
        }
        result = subprocess.run(
            ["/bin/sh", str(ROOT / "install.sh")],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        installed = install_home / "skill"
        self.assertTrue((installed / "SKILL.md").is_file())
        self.uninstall(installed)


if __name__ == "__main__":
    unittest.main()
