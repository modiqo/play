from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from scripts.lib.play.preflight import SCHEMA, inspect


class PreflightTest(unittest.TestCase):
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
    def test_clean_exit_without_ok_email_is_not_authenticated(
        self, _which: MagicMock, run_command: MagicMock
    ) -> None:
        # rote whoami can exit 0 while reporting it is not logged in.
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
        self.assertIn("codex plugin add play@play-skills", payload["setup_commands"])

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
