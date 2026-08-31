from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.lib.play.preflight import SCHEMA, _has_skill, harness_skill_roots, inspect


class PreflightTest(unittest.TestCase):
    def test_missing_skill_root_is_empty_instead_of_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "absent" / "skills"

            self.assertFalse(_has_skill(missing, "rote"))

    def test_codex_marketplace_skill_caches_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary) / ".codex"
            play = codex_home / "plugins/cache/play-skills/play/0.4.2/skills/play"
            rote = codex_home / "plugins/cache/rote-skills/rote/0.68.0/skills/rote"
            play.mkdir(parents=True)
            rote.mkdir(parents=True)
            (play / "SKILL.md").write_text("---\nname: play\n---\n")
            (rote / "SKILL.md").write_text("---\nname: rote\n---\n")

            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                roots = harness_skill_roots()["codex"]

            self.assertIn(play.parent, roots)
            self.assertIn(rote.parent, roots)

    @patch("scripts.lib.play.preflight.shutil.which", return_value=None)
    def test_missing_rote_returns_harness_setup_commands(self, _which: MagicMock) -> None:
        payload = inspect("codex")

        self.assertEqual(SCHEMA, payload["schema"])
        self.assertFalse(payload["ready"])
        self.assertIn("codex plugin marketplace add modiqo/rote-skills", payload["setup_commands"])

    @patch("scripts.lib.play.preflight.run")
    @patch("scripts.lib.play.preflight.shutil.which", return_value="/bin/rote")
    def test_ready_requires_identity_and_play_capability(
        self, _which: MagicMock, run_command: MagicMock
    ) -> None:
        run_command.side_effect = [
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
            MagicMock(returncode=0, stdout="rote play\nUSAGE\n", stderr=""),
        ]

        payload = inspect("claude")

        self.assertTrue(payload["ready"])
        self.assertEqual([], payload["setup_commands"])

    @patch("scripts.lib.play.preflight.run")
    @patch("scripts.lib.play.preflight.shutil.which", return_value="/bin/rote")
    def test_legacy_logout_output_is_not_authenticated(
        self, _which: MagicMock, run_command: MagicMock
    ) -> None:
        # Older Rote versions could exit 0 while reporting that login is required.
        run_command.side_effect = [
            MagicMock(
                returncode=0,
                stdout="@@status\nerror: Not logged in\n@@next\n- rote login\n",
                stderr="",
            ),
            MagicMock(returncode=0, stdout="rote play\nUSAGE\n", stderr=""),
        ]

        payload = inspect("claude")

        self.assertFalse(payload["ready"])
        authenticated = next(
            check for check in payload["checks"] if check["id"] == "authenticated"
        )
        self.assertFalse(authenticated["ok"])
        self.assertIn("Not logged in", authenticated["detail"])

    @patch("scripts.lib.play.preflight.run")
    @patch("scripts.lib.play.preflight.shutil.which", return_value="/bin/rote")
    def test_silent_identity_check_is_authenticated(
        self, _which: MagicMock, run_command: MagicMock
    ) -> None:
        run_command.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="rote play\nUSAGE\n", stderr=""),
        ]

        payload = inspect("claude")

        authenticated = next(
            check for check in payload["checks"] if check["id"] == "authenticated"
        )
        self.assertTrue(authenticated["ok"])
        self.assertEqual("Rote authentication verified.", authenticated["detail"])

    @patch("scripts.lib.play.preflight.inspect_harnesses")
    @patch("scripts.lib.play.preflight.run")
    @patch("scripts.lib.play.preflight.shutil.which")
    def test_missing_play_launcher_is_distinct_from_ready_rote(
        self,
        which: MagicMock,
        run_command: MagicMock,
        inspect_harnesses: MagicMock,
    ) -> None:
        which.side_effect = lambda name: "/bin/rote" if name == "rote" else None
        run_command.side_effect = [
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
            MagicMock(returncode=0, stdout="rote play\nUSAGE\n", stderr=""),
        ]
        inspect_harnesses.return_value = [
            {
                "id": "codex",
                "label": "Codex",
                "rote_skills_installed": True,
                "play_skill_installed": True,
                "selected": True,
            }
        ]

        payload = inspect("codex")

        self.assertFalse(payload["ready"])
        launcher = next(
            check for check in payload["checks"] if check["id"] == "play_machine_on_path"
        )
        self.assertFalse(launcher["ok"])
        self.assertEqual("python-entrypoint", payload["runtime"]["implementation"])
        self.assertEqual("multiple", payload["install_target_prompt"]["selection"])
        self.assertTrue(
            any("play-activate" in command for command in payload["setup_commands"])
        )
        self.assertTrue(any("/skills" in command for command in payload["setup_commands"]))

    @patch("scripts.lib.play.preflight.importlib.util.find_spec", return_value=None)
    @patch("scripts.lib.play.preflight.inspect_harnesses")
    @patch("scripts.lib.play.preflight.run")
    @patch("scripts.lib.play.preflight.shutil.which")
    def test_runtime_bootstrap_requires_uv_or_pinned_environment(
        self,
        which: MagicMock,
        run_command: MagicMock,
        inspect_harnesses: MagicMock,
        _find_spec: MagicMock,
    ) -> None:
        which.side_effect = lambda name: f"/bin/{name}" if name in {"rote", "play-machine"} else None
        run_command.side_effect = [
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
            MagicMock(returncode=0, stdout="rote play\nUSAGE\n", stderr=""),
        ]
        inspect_harnesses.return_value = [
            {
                "id": "codex",
                "label": "Codex",
                "rote_skills_installed": True,
                "play_skill_installed": True,
                "selected": True,
            }
        ]

        payload = inspect("codex")

        environment = next(
            check
            for check in payload["checks"]
            if check["id"] == "play_python_environment"
        )
        self.assertFalse(environment["ok"])
        self.assertTrue(
            any("Install uv" in command for command in payload["setup_commands"])
        )


if __name__ == "__main__":
    unittest.main()
