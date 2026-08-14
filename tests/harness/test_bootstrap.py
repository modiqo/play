from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

from scripts.lib.play.bootstrap import (
    Step,
    Progress,
    _accept_identity_only_preflight,
    _parallel_harness_work,
    _fallback_skill_config_entries,
    _render_status_card,
    _result_step,
    _rote_skill_command,
    apply,
    build_plan,
    codex_disabled_play_entries,
    codex_play_enablement_step,
    converge_play_marketplace,
    install_hooks,
    main,
)


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

    def test_rote_skill_targets_cover_added_harnesses(self) -> None:
        self.assertEqual(
            [
                "rote",
                "install",
                "skill",
                "--target",
                "kimi-code-cli",
                "--target",
                "hermes-agent",
                "--target",
                "opencode",
                "--target",
                "agents-md",
                "--personal",
                "--package",
                "*",
                "--force",
            ],
            _rote_skill_command(
                "rote", ["kimi", "hermes", "opencode", "deepseek"]
            ),
        )

    @patch("scripts.lib.play.bootstrap.resolve_rote", return_value="/bin/rote")
    @patch("scripts.lib.play.bootstrap.shutil.which")
    def test_plan_selects_top_k_and_skips_current_skill_providers(
        self, which: MagicMock, _resolve_rote: MagicMock
    ) -> None:
        which.side_effect = lambda name: f"/bin/{name}" if name in {"codex", "claude", "kimi"} else None
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(returncode=0, stdout="version: 1.2.3\n", stderr=""),
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
            MagicMock(returncode=0, stdout="You are on the latest version!\n", stderr=""),
        ]

        for root in (self.home / ".codex" / "skills", self.home / ".claude" / "skills"):
            skill = root / "rote"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: rote\n---\n", encoding="utf-8")

        plan = build_plan(top_k=2, runner=runner)

        self.assertEqual(["codex", "claude"], plan["selected_harnesses"])
        convergence = next(action for action in plan["actions"] if action["id"] == "converge_rote_skills")
        self.assertIsNone(convergence["command"])
        self.assertEqual([], convergence["targets"])
        self.assertEqual("keep_rote_current", plan["actions"][0]["id"])
        marketplace = next(
            action
            for action in plan["actions"]
            if action["id"] == "converge_play_marketplaces"
        )
        self.assertEqual(["codex", "claude"], marketplace["targets"])
        self.assertEqual(
            ["codex", "plugin", "marketplace", "upgrade", "play-skills"],
            marketplace["commands"]["codex"][0],
        )
        self.assertEqual(
            ["claude", "plugin", "marketplace", "update", "play-skills"],
            marketplace["commands"]["claude"][0],
        )
        self.assertEqual("current", plan["rote"]["update"]["status"])
        skill_status = {item["provider"]: item for item in plan["rote_skills"]}
        self.assertEqual("keep", skill_status["codex"]["recommended_action"])
        self.assertEqual("keep", skill_status["claude-code"]["recommended_action"])

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

    def test_codex_marketplace_convergence_refreshes_removes_and_reinstalls(self) -> None:
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(
                returncode=0,
                stdout=json.dumps({"marketplaces": [{"name": "play-skills"}]}),
                stderr="",
            ),
            MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "installed": [
                            {
                                "pluginId": "play@play-skills",
                                "version": "0.3.0",
                                "enabled": True,
                            }
                        ]
                    }
                ),
                stderr="",
            ),
            MagicMock(returncode=0, stdout="updated\n", stderr=""),
            MagicMock(returncode=0, stdout="removed\n", stderr=""),
            MagicMock(returncode=0, stdout="installed\n", stderr=""),
            MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "installed": [
                            {
                                "pluginId": "play@play-skills",
                                "version": "0.4.6",
                                "enabled": True,
                            }
                        ]
                    }
                ),
                stderr="",
            ),
        ]

        steps = converge_play_marketplace(
            "codex", "/bin/codex", expected_version="0.4.6", runner=runner
        )

        commands = [call.args[0] for call in runner.call_args_list]
        self.assertEqual(
            [
                "/bin/codex",
                "plugin",
                "marketplace",
                "upgrade",
                "play-skills",
            ],
            commands[2],
        )
        self.assertEqual(
            ["/bin/codex", "plugin", "remove", "play@play-skills"], commands[3]
        )
        self.assertEqual(
            ["/bin/codex", "plugin", "add", "play@play-skills"], commands[4]
        )
        self.assertEqual("completed", steps[-1].status)
        self.assertIn("0.4.6", steps[-1].detail)

    def test_claude_marketplace_convergence_refreshes_user_scope(self) -> None:
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(
                returncode=0,
                stdout=json.dumps([{"name": "play-skills"}]),
                stderr="",
            ),
            MagicMock(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "id": "play@play-skills",
                            "version": "0.1.0",
                            "enabled": True,
                            "scope": "user",
                        }
                    ]
                ),
                stderr="",
            ),
            MagicMock(returncode=0, stdout="updated\n", stderr=""),
            MagicMock(returncode=0, stdout="removed\n", stderr=""),
            MagicMock(returncode=0, stdout="installed\n", stderr=""),
            MagicMock(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "id": "play@play-skills",
                            "version": "0.4.6",
                            "enabled": True,
                            "scope": "user",
                        }
                    ]
                ),
                stderr="",
            ),
        ]

        steps = converge_play_marketplace(
            "claude", "/bin/claude", expected_version="0.4.6", runner=runner
        )

        commands = [call.args[0] for call in runner.call_args_list]
        self.assertEqual(
            [
                "/bin/claude",
                "plugin",
                "marketplace",
                "update",
                "play-skills",
            ],
            commands[2],
        )
        self.assertEqual(
            [
                "/bin/claude",
                "plugin",
                "uninstall",
                "play@play-skills",
                "--scope",
                "user",
            ],
            commands[3],
        )
        self.assertEqual(
            [
                "/bin/claude",
                "plugin",
                "install",
                "play@play-skills",
                "--scope",
                "user",
            ],
            commands[4],
        )
        self.assertEqual("completed", steps[-1].status)

    def test_current_plugin_uses_two_read_only_probes_without_reinstall(self) -> None:
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(
                returncode=0,
                stdout=json.dumps({"marketplaces": [{"name": "play-skills"}]}),
                stderr="",
            ),
            MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "installed": [
                            {
                                "pluginId": "play@play-skills",
                                "version": "0.4.6",
                                "enabled": True,
                            }
                        ]
                    }
                ),
                stderr="",
            ),
        ]

        steps = converge_play_marketplace(
            "codex", "/bin/codex", expected_version="0.4.6", runner=runner
        )

        self.assertEqual(2, runner.call_count)
        self.assertEqual("unchanged", steps[-1].status)
        self.assertIn("already installed", steps[-1].detail)

    def test_progress_redraws_one_terminal_line_with_elapsed_time(self) -> None:
        stream = StringIO()
        progress = Progress(
            stream,
            heartbeat_seconds=0.01,
            interactive=True,
            insights=("Workflow fit first.", "Immediate value wins."),
            insight_seconds=0.01,
        )

        def work() -> str:
            time.sleep(0.025)
            return "done"

        self.assertEqual("done", progress.call("Checking things", work))

        rendered = stream.getvalue()
        self.assertIn("✦ Workflow fit first.\n◐ Checking things ·", rendered)
        self.assertIn("✦ Immediate value wins.", rendered)
        self.assertIn("\033[1A\r\033[2K", rendered)
        self.assertRegex(rendered, r"✓ Checking things \(\d+\.\ds\)")
        self.assertEqual(1, rendered.count("✓ Checking things"))

    def test_progress_omits_repeating_heartbeats_when_redirected(self) -> None:
        stream = StringIO()
        progress = Progress(
            stream,
            heartbeat_seconds=0.01,
            interactive=False,
            insights=("This should stay out of redirected logs.",),
        )

        progress.call("Checking things", lambda: time.sleep(0.025))

        rendered = stream.getvalue()
        self.assertEqual(1, rendered.count("◐ Checking things"))
        self.assertNotIn("Checking things ·", rendered)
        self.assertNotIn("redirected logs", rendered)
        self.assertEqual(2, rendered.count("\n"))

    def test_parallel_progress_shares_one_transient_terminal_line(self) -> None:
        stream = StringIO()
        progress = Progress(
            stream,
            heartbeat_seconds=0,
            interactive=True,
            insights=("A workflow should pay rent quickly.",),
        )

        codex = progress.begin("Integrating Codex")
        claude = progress.begin("Integrating Claude Code")
        progress.finish(codex)
        progress.finish(claude)

        rendered = stream.getvalue()
        self.assertIn(
            "◐ Integrating Codex; Integrating Claude Code · 0s", rendered
        )
        self.assertIn("✦ A workflow should pay rent quickly.", rendered)
        self.assertEqual(1, rendered.count("✓ Integrating Codex"))
        self.assertEqual(1, rendered.count("✓ Integrating Claude Code"))

    def test_parallel_harness_work_starts_jobs_concurrently(self) -> None:
        barrier = threading.Barrier(3)

        def work(harness: str) -> str:
            barrier.wait(timeout=1)
            time.sleep(0.02)
            return harness

        started = time.perf_counter()
        results = _parallel_harness_work(["codex", "claude", "kimi"], work)

        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertEqual(
            {"codex": "codex", "claude": "claude", "kimi": "kimi"}, results
        )

    @patch("scripts.lib.play.bootstrap.resolve_rote", return_value="/bin/rote")
    @patch("scripts.lib.play.bootstrap.shutil.which")
    def test_plan_rejects_more_than_three_harnesses(
        self, which: MagicMock, _resolve_rote: MagicMock
    ) -> None:
        which.return_value = "/bin/harness"
        with self.assertRaisesRegex(Exception, "at most 3 harnesses"):
            build_plan(
                requested=["codex", "claude", "kimi", "hermes"],
                runner=MagicMock(),
            )
        with self.assertRaisesRegex(Exception, "top-k cannot exceed 3"):
            build_plan(top_k=4, runner=MagicMock())

    def test_codex_disabled_play_skill_override_is_detected(self) -> None:
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            '[[skills.config]]\npath = "/tmp/plugins/cache/play-skills/play/0.3.0/skills/play/SKILL.md"\nenabled = false\n',
            encoding="utf-8",
        )

        self.assertEqual(
            ["/tmp/plugins/cache/play-skills/play/0.3.0/skills/play/SKILL.md"],
            codex_disabled_play_entries(),
        )
        step = codex_play_enablement_step()
        self.assertEqual("human_action_required", step.status)
        self.assertIn("/skills", step.detail)

    def test_python_310_fallback_reads_only_skills_config_tables(self) -> None:
        entries = _fallback_skill_config_entries(
            '[other]\nenabled = false\n\n'
            '[[skills.config]]\nname = "play"\nenabled = false\n\n'
            '[[skills.config]]\nname = "other"\nenabled = true\n'
        )

        self.assertEqual(
            [
                {"name": "play", "enabled": False},
                {"name": "other", "enabled": True},
            ],
            entries,
        )

    def test_status_card_gives_harness_specific_first_steps(self) -> None:
        rendered = _render_status_card(
            {
                "status": "action_required",
                "run_id": "card-run",
                "selected_harnesses": ["codex", "claude"],
                "steps": [
                    {
                        "id": "enable_play_skill",
                        "status": "human_action_required",
                        "detail": "Open /skills, enable Play, then restart Codex.",
                        "target": "codex",
                    },
                    {
                        "id": "verify_play_plugin",
                        "status": "completed",
                        "detail": "Play is ready.",
                        "target": "claude",
                    },
                ],
                "report_paths": {
                    "markdown": "/tmp/card-run.md",
                    "json": "/tmp/card-run.json",
                },
            }
        )

        self.assertIn("Status: READY — ACTION REQUIRED", rendered)
        self.assertIn("Codex          ACTION REQUIRED", rendered)
        self.assertIn("Claude Code    READY", rendered)
        self.assertIn("Start Codex: codex", rendered)
        self.assertIn("type: $play", rendered)
        self.assertIn("Start Claude Code: claude", rendered)
        self.assertIn("type: /play", rendered)
        self.assertIn("$play whats new", rendered)
        self.assertIn("/play run <Play name>", rendered)
        self.assertIn("/tmp/card-run.md", rendered)

    def test_status_card_uses_native_invocations_for_added_harnesses(self) -> None:
        rendered = _render_status_card(
            {
                "status": "completed",
                "run_id": "more-harnesses",
                "selected_harnesses": ["kimi", "hermes", "opencode", "deepseek"],
                "steps": [],
            }
        )

        self.assertIn("Start Kimi: kimi", rendered)
        self.assertIn("type: /skill:play", rendered)
        self.assertIn("Start Hermes Agent: hermes", rendered)
        self.assertIn("Start OpenCode: opencode", rendered)
        self.assertIn("Start DeepSeek Harness (preview): dsh web", rendered)
        self.assertIn("type: /play", rendered)

    def test_status_card_frames_missing_identity_as_guided_onboarding(self) -> None:
        rendered = _render_status_card(
            {
                "status": "onboarding_required",
                "run_id": "sign-in-run",
                "selected_harnesses": ["codex"],
                "steps": [
                    {
                        "id": "rote_identity",
                        "status": "onboarding_required",
                        "detail": "Sign in or create a Rote account.",
                    }
                ],
            }
        )

        self.assertIn("Status: READY — SIGN IN TO CONTINUE", rendered)
        self.assertIn("Codex          READY", rendered)
        self.assertIn("Sign in to start", rendered)
        self.assertIn("rote login --provider google", rendered)
        self.assertIn("rote login --provider github", rendered)
        self.assertNotIn("INCOMPLETE", rendered)

    def test_status_card_keeps_structured_command_output_in_report(self) -> None:
        verbose = json.dumps(
            {
                "error": "plugin failed",
                "diagnostics": [{"line": index, "detail": "x" * 40} for index in range(20)],
            },
            indent=2,
        )
        rendered = _render_status_card(
            {
                "status": "blocked",
                "run_id": "quiet-card",
                "selected_harnesses": ["claude"],
                "steps": [
                    {
                        "id": "install_current_play_plugin",
                        "status": "failed",
                        "detail": verbose,
                        "target": "claude",
                    }
                ],
                "report_paths": {
                    "markdown": "/tmp/quiet-card.md",
                    "json": "/tmp/quiet-card.json",
                },
            }
        )

        self.assertNotIn("diagnostics", rendered)
        self.assertNotIn("plugin failed", rendered)
        self.assertIn("see the detailed JSON report", rendered)
        self.assertIn("/tmp/quiet-card.json", rendered)

    def test_failed_command_report_preserves_stdout_and_stderr(self) -> None:
        step = _result_step(
            "install_play",
            subprocess.CompletedProcess(
                ["install-all"], 1, "activation started\n", "launcher missing\n"
            ),
            ["install-all"],
        )

        self.assertEqual("failed", step.status)
        self.assertIn("stdout:\nactivation started", step.detail)
        self.assertIn("stderr:\nlauncher missing", step.detail)

    def test_identity_only_preflight_is_onboarding_eligible(self) -> None:
        payload = {
            "checks": [
                {"id": "play_machine_on_path", "ok": True},
                {"id": "authenticated", "ok": False},
            ]
        }
        result = subprocess.CompletedProcess(
            ["play-preflight"], 2, json.dumps(payload), ""
        )

        normalized = _accept_identity_only_preflight(result)

        self.assertEqual(0, normalized.returncode)

    def test_preflight_with_activation_failure_remains_failed(self) -> None:
        payload = {
            "checks": [
                {"id": "play_machine_on_path", "ok": False},
                {"id": "authenticated", "ok": False},
            ]
        }
        result = subprocess.CompletedProcess(
            ["play-preflight"], 2, json.dumps(payload), ""
        )

        normalized = _accept_identity_only_preflight(result)

        self.assertEqual(2, normalized.returncode)

    @patch(
        "scripts.lib.play.bootstrap.converge_play_marketplace",
        return_value=[
            Step(
                "verify_play_plugin",
                "completed",
                "Play 0.4.6 is installed and enabled.",
                target="codex",
            )
        ],
    )
    @patch("scripts.lib.play.bootstrap.resolve_rote", return_value="/bin/rote")
    def test_apply_existing_rote_updates_converges_installs_hooks_and_verifies(
        self, _resolve_rote: MagicMock, _converge_marketplace: MagicMock
    ) -> None:
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(returncode=0, stdout="version: 1.0.0\n", stderr=""),
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
            MagicMock(returncode=0, stdout="Rote 1.1.0 is available\n", stderr=""),
            MagicMock(returncode=0, stdout="updated to 1.1.0\n", stderr=""),
            MagicMock(returncode=0, stdout="installed all skills\n", stderr=""),
            MagicMock(returncode=0, stdout="Play ready\n", stderr=""),
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
            MagicMock(returncode=0, stdout='{"ready":true}\n', stderr=""),
            MagicMock(returncode=0, stdout="version: 1.1.0\n", stderr=""),
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
            MagicMock(returncode=0, stdout="You are on the latest version!\n", stderr=""),
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
                "--target",
                "codex",
                "--personal",
                "--package",
                "*",
                "--force",
            ],
            commands,
        )
        self.assertEqual("1.0.0", report["rote"]["before"]["version"])
        self.assertEqual("1.1.0", report["rote"]["after"]["version"])
        self.assertTrue((self.home / ".codex" / "hooks.json").is_file())
        step_ids = [step["id"] for step in report["steps"]]
        self.assertLess(
            step_ids.index("verify_play_plugin"), step_ids.index("install_play")
        )
        _converge_marketplace.assert_called_once()
        self.assertEqual(
            "0.4.6", _converge_marketplace.call_args.kwargs["expected_version"]
        )

    @patch("scripts.lib.play.bootstrap._confirm", side_effect=[True, True])
    @patch("scripts.lib.play.bootstrap.apply")
    @patch("scripts.lib.play.bootstrap.build_plan")
    def test_guided_install_separately_confirms_plan_and_missing_rote(
        self,
        build: MagicMock,
        apply_plan: MagicMock,
        confirm: MagicMock,
    ) -> None:
        build.return_value = {
            "plan_id": "sha256:guided",
            "selected_harnesses": ["codex"],
            "rote": {
                "path": None,
                "version": None,
                "update": {
                    "status": "not_installed",
                    "detail": "Rote is not installed.",
                },
            },
            "rote_skills": [
                {
                    "label": "Codex",
                    "root": str(self.home / ".codex" / "skills"),
                    "installed": False,
                    "skill_count": 0,
                    "recommended_action": "install",
                }
            ],
            "actions": [
                {
                    "id": "install_rote",
                    "effect": "downloads and installs executable code",
                    "approval_required": True,
                }
            ],
        }
        apply_plan.return_value = {
            "run_id": "guided-run",
            "status": "completed",
            "plan_id": "sha256:guided",
            "started_at": "2026-08-13T00:00:00+00:00",
            "finished_at": "2026-08-13T00:00:01+00:00",
            "selected_harnesses": ["codex"],
            "steps": [],
            "restart": "Restart Codex.",
        }

        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            result = main(["install", "--harness", "codex", "--run-id", "guided-run"])

        self.assertEqual(0, result)
        self.assertEqual(2, confirm.call_count)
        self.assertIn("exact Play bootstrap plan", confirm.call_args_list[0].args[0])
        self.assertIn("https://getrote.dev/install", confirm.call_args_list[1].args[0])
        apply_plan.assert_called_once_with(
            ROOT,
            top_k=3,
            requested=["codex"],
            approve_remote_installer=True,
            run_id="guided-run",
            expected_plan_id="sha256:guided",
            prepared_plan=build.return_value,
            progress=ANY,
        )


if __name__ == "__main__":
    unittest.main()
