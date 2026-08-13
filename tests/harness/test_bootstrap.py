from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.lib.play.bootstrap import apply, build_plan, install_hooks


ROOT = Path(__file__).resolve().parents[2]


class BootstrapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.environment = {
            "HOME": str(self.home),
            "CODEX_HOME": str(self.home / ".codex"),
            "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
            "CURSOR_CONFIG_DIR": str(self.home / ".cursor"),
            "KIMI_CONFIG_DIR": str(self.home / ".kimi"),
            "AGENTS_HOME": str(self.home / ".agents"),
            "PLAY_BOOTSTRAP_STATE": str(self.home / "state"),
        }
        self.environment_patch = patch.dict(os.environ, self.environment, clear=False)
        self.environment_patch.start()

    def tearDown(self) -> None:
        self.environment_patch.stop()
        self.temporary.cleanup()

    @patch("scripts.lib.play.bootstrap.resolve_rote", return_value="/bin/rote")
    @patch("scripts.lib.play.bootstrap.shutil.which")
    def test_plan_selects_top_k_and_requires_complete_skill_convergence(
        self, which: MagicMock, _resolve_rote: MagicMock
    ) -> None:
        which.side_effect = lambda name: f"/bin/{name}" if name in {"codex", "claude", "kimi"} else None
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(returncode=0, stdout="version: 1.2.3\n", stderr=""),
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
        ]

        plan = build_plan(top_k=2, runner=runner)

        self.assertEqual(["codex", "claude"], plan["selected_harnesses"])
        convergence = next(action for action in plan["actions"] if action["id"] == "converge_rote_skills")
        self.assertEqual(
            ["rote", "install", "skill", "--provider", "all", "--personal", "--package", "*"],
            convergence["command"],
        )
        self.assertEqual("update_rote", plan["actions"][0]["id"])

    def test_codex_hooks_replace_only_managed_play_entries_and_create_backup(self) -> None:
        path = self.home / ".codex" / "hooks.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {"hooks": [{"command": "keep-me", "type": "command"}]},
                            {"hooks": [{"command": "/old/play-intercept prompt"}]},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        step = install_hooks("codex", ROOT, run_id="test-run")

        self.assertEqual("completed", step.status)
        value = json.loads(path.read_text(encoding="utf-8"))
        prompt = value["hooks"]["UserPromptSubmit"]
        self.assertEqual(2, len(prompt))
        self.assertIn("keep-me", json.dumps(prompt))
        self.assertIn(str(ROOT / "scripts" / "bin" / "play-intercept"), json.dumps(prompt))
        self.assertTrue(path.with_name("hooks.json.play-backup-test-run").is_file())
        self.assertIn("Stop", value["hooks"])
        self.assertIn("SessionStart", value["hooks"])

    def test_cursor_hooks_use_native_flat_schema(self) -> None:
        step = install_hooks("cursor", ROOT, run_id="cursor-run")

        self.assertEqual("completed", step.status)
        path = self.home / ".cursor" / "hooks.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(1, value["version"])
        self.assertIn("play-intercept", value["hooks"]["beforeSubmitPrompt"][0]["command"])
        self.assertIn("play-intercept", value["hooks"]["stop"][0]["command"])
        self.assertIn("play-inbox", value["hooks"]["sessionStart"][0]["command"])

    @patch("scripts.lib.play.bootstrap.resolve_rote", return_value=None)
    def test_apply_without_remote_approval_stops_and_writes_both_reports(
        self, _resolve_rote: MagicMock
    ) -> None:
        report = apply(
            ROOT,
            requested=["codex"],
            runner=MagicMock(),
            run_id="approval-run",
        )

        self.assertEqual("blocked", report["status"])
        self.assertEqual("approval_required", report["steps"][0]["status"])
        self.assertTrue(Path(report["report_paths"]["json"]).is_file())
        self.assertTrue(Path(report["report_paths"]["markdown"]).is_file())

    @patch("scripts.lib.play.bootstrap.resolve_rote", return_value="/bin/rote")
    def test_apply_existing_rote_updates_converges_installs_hooks_and_verifies(
        self, _resolve_rote: MagicMock
    ) -> None:
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(returncode=0, stdout="version: 1.0.0\n", stderr=""),
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
            MagicMock(returncode=0, stdout="updated to 1.1.0\n", stderr=""),
            MagicMock(returncode=0, stdout="installed all skills\n", stderr=""),
            MagicMock(returncode=0, stdout="Play ready\n", stderr=""),
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
            MagicMock(returncode=0, stdout='{"ready":true}\n', stderr=""),
            MagicMock(returncode=0, stdout="version: 1.1.0\n", stderr=""),
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
        ]

        report = apply(
            ROOT,
            requested=["codex"],
            runner=runner,
            run_id="complete-run",
        )

        self.assertEqual("completed", report["status"])
        commands = [call.args[0] for call in runner.call_args_list]
        self.assertIn(["/bin/rote", "self-update", "--yes"], commands)
        self.assertIn(
            [
                "/bin/rote",
                "install",
                "skill",
                "--provider",
                "all",
                "--personal",
                "--package",
                "*",
            ],
            commands,
        )
        self.assertEqual("1.0.0", report["rote"]["before"]["version"])
        self.assertEqual("1.1.0", report["rote"]["after"]["version"])
        self.assertTrue((self.home / ".codex" / "hooks.json").is_file())


if __name__ == "__main__":
    unittest.main()
