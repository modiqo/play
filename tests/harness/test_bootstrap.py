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
    _identity_gate,
    _official_rote_install_command,
    _render_status_card,
    _result_step,
    _rote_compatibility_step,
    _run_login_visible,
    _run_visible,
    _rote_skill_command,
    _warm_public_play_cache,
    _verify_prompt_intercept,
    apply,
    backup_play_state,
    build_restore_plan,
    build_plan,
    codex_disabled_play_entries,
    codex_play_enablement_step,
    converge_play_marketplace,
    install_hooks,
    install_journey_model_assets,
    list_play_backups,
    prune_play_backups,
    remove_portable_play_hooks,
    restore_play_state,
    main,
    run,
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

    def test_journey_model_assets_seed_config_and_refresh_catalog(self) -> None:
        owner = self.home / ".play"
        first = install_journey_model_assets(ROOT, home=owner)
        config = owner / "model-config.yaml"
        catalog = owner / "cache" / "model_prices_and_context_window.json"
        self.assertEqual("completed", first.status)
        self.assertIn("name: codex", config.read_text(encoding="utf-8"))
        self.assertIn("gpt-5", json.loads(catalog.read_text(encoding="utf-8")))
        config.write_text("schema: play.model-config/v1\ncustom: retained\n", encoding="utf-8")

        second = install_journey_model_assets(ROOT, home=owner)

        self.assertIn("custom: retained", config.read_text(encoding="utf-8"))
        self.assertEqual("unchanged", second.status)
        self.assertFalse(second.changed)

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

    def test_official_rote_installer_cannot_read_the_parent_terminal(self) -> None:
        self.assertEqual(
            [
                "bash",
                "-c",
                "ROTE_YES=1 ROTE_FULL=1 bash -c \"$(curl --proto '=https' --tlsv1.2 -fsSL https://getrote.dev/install)\" </dev/null",
            ],
            _official_rote_install_command(),
        )

    def test_rote_compatibility_requires_in_place_mcp_lifecycle_support(self) -> None:
        old = _rote_compatibility_step(
            "/bin/rote",
            MagicMock(
                return_value=MagicMock(
                    returncode=0, stdout="version: 0.69.1\n", stderr=""
                )
            ),
        )
        current = _rote_compatibility_step(
            "/bin/rote",
            MagicMock(
                return_value=MagicMock(
                    returncode=0, stdout="version: 0.69.2\n", stderr=""
                )
            ),
        )

        self.assertEqual("failed", old.status)
        self.assertIn("rote self-update --yes", old.detail)
        self.assertEqual("unchanged", current.status)
        self.assertIn("in-place credential reauthorization", current.detail)

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
        hooks = next(action for action in plan["actions"] if action["id"] == "install_hooks")
        self.assertEqual([], hooks["native_plugin_targets"])
        self.assertEqual(["codex", "claude"], hooks["portable_targets"])
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
        self.assertIn("milestone-nudge", json.dumps(value["hooks"]["Stop"]))
        self.assertIn("SessionStart", value["hooks"])

    def test_codex_hook_reinstall_resets_only_play_disabled_state(self) -> None:
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
        config = self.home / ".codex" / "config.toml"
        config.write_text(
            f'[hooks.state."{path}:user_prompt_submit:0:0"]\n'
            'trusted_hash = "sha256:keep"\n'
            "enabled = false\n\n"
            f'[hooks.state."{path}:user_prompt_submit:1:0"]\n'
            'trusted_hash = "sha256:play"\n'
            "enabled = false\n\n"
            '[hooks.state."play@play-skills:hooks/hooks.json:user_prompt_submit:0:0"]\n'
            'trusted_hash = "sha256:plugin-play"\n'
            "enabled = false\n",
            encoding="utf-8",
        )

        step = install_hooks("codex", ROOT, run_id="replace-hooks")

        self.assertEqual("completed", step.status)
        text = config.read_text(encoding="utf-8")
        self.assertIn('trusted_hash = "sha256:keep"\nenabled = false', text)
        self.assertIn('trusted_hash = "sha256:play"\nenabled = true', text)
        self.assertIn('trusted_hash = "sha256:plugin-play"\nenabled = true', text)
        self.assertIn("prompt hook smoke check passed", step.detail)

    def test_codex_hooks_are_backed_up_and_replaced_even_when_current(self) -> None:
        first = install_hooks("codex", ROOT, run_id="first-hooks")
        before = (self.home / ".codex" / "hooks.json").read_text(encoding="utf-8")

        second = install_hooks("codex", ROOT, run_id="second-hooks")

        self.assertEqual("completed", first.status)
        self.assertEqual("completed", second.status)
        backup = self.home / ".codex" / "hooks.json.play-backup-second-hooks"
        self.assertEqual(before, backup.read_text(encoding="utf-8"))

    def test_prompt_hook_resolves_a_verified_cached_catalog_entry(self) -> None:
        cache = self.home / ".rote-play" / "inbox-cache.json"
        cache.parent.mkdir(parents=True)
        cache.write_text(
            json.dumps(
                {
                    "schema": "play.inbox-cache/v1",
                    "catalog_complete": True,
                    "catalog": [
                        {
                            "reference": "modiqo/retrieve-rideshare-receipts",
                            "name": "retrieve-rideshare-receipts",
                            "description": "Retrieve Uber and Lyft receipts from email.",
                            "visibility": "public",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        _verify_prompt_intercept(ROOT, verify_catalog=True)

    def test_cursor_hooks_use_native_flat_schema(self) -> None:
        step = install_hooks("cursor", ROOT, run_id="cursor-run")

        self.assertEqual("completed", step.status)
        path = self.home / ".cursor" / "hooks.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(1, value["version"])
        self.assertIn("play-intercept", value["hooks"]["beforeSubmitPrompt"][0]["command"])
        self.assertIn("play-intercept", value["hooks"]["stop"][0]["command"])
        self.assertIn("milestone-nudge", value["hooks"]["stop"][0]["command"])
        self.assertIn("play-inbox", value["hooks"]["sessionStart"][0]["command"])

    def test_native_plugin_removes_only_legacy_play_hooks(self) -> None:
        for harness, directory, filename in (
            ("codex", ".codex", "hooks.json"),
            ("claude", ".claude", "settings.json"),
        ):
            with self.subTest(harness=harness):
                path = self.home / directory / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "theme": "dark",
                            "hooks": {
                                "UserPromptSubmit": [
                                    {"hooks": [{"command": "keep-me"}]},
                                    {"hooks": [{"command": "/old/play-intercept prompt"}]},
                                ],
                                "Stop": [
                                    {"hooks": [{"command": "/old/play-intercept settle-nudge"}]}
                                ],
                            },
                        }
                    ),
                    encoding="utf-8",
                )

                step = remove_portable_play_hooks(harness, run_id=f"dedupe-{harness}")

                self.assertEqual("completed", step.status)
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual("dark", value["theme"])
                self.assertEqual(1, len(value["hooks"]["UserPromptSubmit"]))
                self.assertIn("keep-me", json.dumps(value))
                self.assertNotIn("play-intercept", json.dumps(value))
                self.assertNotIn("Stop", value["hooks"])
                self.assertTrue(
                    path.with_name(f"{filename}.play-backup-dedupe-{harness}").is_file()
                )

    def test_native_plugin_hook_removal_is_idempotent(self) -> None:
        path = self.home / ".codex" / "hooks.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"hooks": {}}), encoding="utf-8")

        step = remove_portable_play_hooks("codex", run_id="dedupe-current")

        self.assertEqual("unchanged", step.status)
        self.assertFalse(path.with_name("hooks.json.play-backup-dedupe-current").exists())

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
                                "version": "0.4.36",
                                "enabled": True,
                            }
                        ]
                    }
                ),
                stderr="",
            ),
        ]

        steps = converge_play_marketplace(
            "codex", "/bin/codex", expected_version="0.4.36", runner=runner
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
        self.assertIn("0.4.36", steps[-1].detail)

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
                            "version": "0.4.36",
                            "enabled": True,
                            "scope": "user",
                        }
                    ]
                ),
                stderr="",
            ),
        ]

        steps = converge_play_marketplace(
            "claude", "/bin/claude", expected_version="0.4.36", runner=runner
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

    def test_current_plugin_is_reinstalled_for_full_convergence(self) -> None:
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
                                "version": "0.4.36",
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
                                "version": "0.4.36",
                                "enabled": True,
                            }
                        ]
                    }
                ),
                stderr="",
            ),
        ]

        steps = converge_play_marketplace(
            "codex", "/bin/codex", expected_version="0.4.36", runner=runner
        )

        self.assertEqual(6, runner.call_count)
        self.assertEqual("completed", steps[-1].status)
        self.assertIn("installed, enabled, and healthy", steps[-1].detail)

    def test_byte_current_plugin_skips_marketplace_reinstall(self) -> None:
        expected = self.home / "source-plugin"
        installed = self.home / "installed-plugin"
        expected.mkdir()
        installed.mkdir()
        (expected / "plugin.json").write_text('{"name":"play"}\n', encoding="utf-8")
        (installed / "plugin.json").write_text('{"name":"play"}\n', encoding="utf-8")
        (installed / ".in_use").write_text("runtime marker\n", encoding="utf-8")
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
                                "version": "0.4.36",
                                "enabled": True,
                                "source": {"source": "local", "path": str(installed)},
                            }
                        ]
                    }
                ),
                stderr="",
            ),
        ]

        steps = converge_play_marketplace(
            "codex",
            "/bin/codex",
            expected_version="0.4.36",
            expected_plugin_root=expected,
            runner=runner,
        )

        self.assertEqual(2, runner.call_count)
        self.assertEqual("unchanged", steps[-1].status)
        self.assertIn("byte-current", steps[-1].detail)

    def test_local_codex_marketplace_is_not_sent_to_git_upgrade(self) -> None:
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "marketplaces": [
                            {
                                "name": "play-skills",
                                "marketplaceSource": {
                                    "sourceType": "local",
                                    "source": str(ROOT),
                                },
                            }
                        ]
                    }
                ),
                stderr="",
            ),
            MagicMock(
                returncode=0,
                stdout=json.dumps({"installed": [], "available": []}),
                stderr="",
            ),
            MagicMock(returncode=0, stdout="installed\n", stderr=""),
            MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "installed": [
                            {
                                "pluginId": "play@play-skills",
                                "version": "0.4.40",
                                "enabled": True,
                            }
                        ]
                    }
                ),
                stderr="",
            ),
        ]

        steps = converge_play_marketplace(
            "codex", "/bin/codex", expected_version="0.4.40", runner=runner
        )

        commands = [call.args[0] for call in runner.call_args_list]
        self.assertFalse(any("upgrade" in command for command in commands))
        self.assertEqual(
            ["/bin/codex", "plugin", "add", "play@play-skills"], commands[2]
        )
        self.assertEqual("completed", steps[-1].status)

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
        self.assertIn("✦ Workflow fit first.\r\n◐ Checking things ·", rendered)
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

    def test_progress_cleans_up_terminal_line_when_interrupted(self) -> None:
        stream = StringIO()
        progress = Progress(
            stream,
            heartbeat_seconds=0,
            interactive=True,
            insights=("Interruptions should stay readable.",),
        )

        def interrupt() -> None:
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            progress.call("Installing something", interrupt)

        rendered = stream.getvalue()
        self.assertIn("✗ Installing something", rendered)
        self.assertFalse(progress._line_visible)

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
        self.assertRegex(
            rendered,
            r"[◐◓◑◒] Integrating Codex; Integrating Claude Code · 0s",
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
        self.assertEqual("completed", step.status)
        self.assertIn("plugin now owns enablement", step.detail)
        self.assertNotIn("play/0.3.0", config.read_text(encoding="utf-8"))

    def test_full_install_backup_captures_play_owned_harness_state(self) -> None:
        hooks = self.home / ".codex" / "hooks.json"
        hooks.parent.mkdir(parents=True)
        hooks.write_text('{"hooks": {}}\n', encoding="utf-8")
        config = self.home / ".codex" / "config.toml"
        config.write_text(
            '[[skills.config]]\nname = "play"\nenabled = false\n',
            encoding="utf-8",
        )
        play = self.home / ".codex" / "skills" / "play"
        play.mkdir(parents=True)
        (play / "SKILL.md").write_text("play\n", encoding="utf-8")
        targets = {"codex": {"skill_roots": [str(play.parent)]}}

        manifest_path = backup_play_state(
            ["codex"], targets, run_id="full-overwrite"
        )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual("play.install-backup/v1", manifest["schema"])
        backed_up = {entry["path"] for entry in manifest["entries"]}
        self.assertIn(str(hooks), backed_up)
        self.assertIn(str(config), backed_up)
        self.assertIn(str(play), backed_up)
        self.assertEqual(0o700, manifest_path.parent.stat().st_mode & 0o777)
        self.assertEqual(0o600, manifest_path.stat().st_mode & 0o777)

    def test_install_backup_records_absent_paths_for_exact_restore(self) -> None:
        manifest_path = backup_play_state([], {}, run_id="absent-paths")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual("install", manifest["purpose"])
        self.assertTrue(any(entry["kind"] == "absent" for entry in manifest["entries"]))

    def test_verified_backup_retention_keeps_newest_ten(self) -> None:
        for index in range(12):
            backup_play_state([], {}, run_id=f"retention-{index:02d}")

        removed = prune_play_backups(protect=["retention-11"])
        catalog = list_play_backups()

        self.assertEqual(2, len(removed))
        self.assertEqual(10, len(catalog["backups"]))
        self.assertIn(
            "retention-11", {item["run_id"] for item in catalog["backups"]}
        )

    def test_dossier_restore_is_transactional_and_creates_safety_backup(self) -> None:
        portable = self.home / ".local" / "share" / "modiqo" / "play" / "skill"
        portable.mkdir(parents=True)
        state = portable / "state.txt"
        state.write_text("before\n", encoding="utf-8")
        manifest_path = backup_play_state([], {}, run_id="install-before-update")
        dossier = self.home / "state" / "runs" / "install-before-update.json"
        dossier.parent.mkdir(parents=True)
        dossier.write_text(
            json.dumps(
                {
                    "schema": "play.bootstrap-report/v1",
                    "steps": [
                        {
                            "id": "backup_play_state",
                            "status": "completed",
                            "evidence": str(manifest_path),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        state.write_text("after\n", encoding="utf-8")

        plan = build_restore_plan(dossier=dossier)
        report = restore_play_state(plan)

        self.assertEqual("before\n", state.read_text(encoding="utf-8"))
        self.assertEqual("completed", report["status"])
        self.assertTrue(Path(report["safety_backup_manifest"]).is_file())
        self.assertTrue(Path(report["report_paths"]["json"]).is_file())

    def test_restore_replaces_only_play_owned_hooks_in_shared_config(self) -> None:
        hooks = self.home / ".codex" / "hooks.json"
        hooks.parent.mkdir(parents=True)
        hooks.write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {"command": "user-hook-before"},
                            {"command": "/old/play-intercept prompt"},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        backup_play_state(["codex"], {}, run_id="shared-hook-state")
        hooks.write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {"command": "user-hook-after"},
                            {"command": "/new/play-intercept prompt"},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        restore_play_state(build_restore_plan(backup_run_id="shared-hook-state"))
        entries = json.loads(hooks.read_text(encoding="utf-8"))["hooks"][
            "UserPromptSubmit"
        ]

        self.assertEqual(
            [
                {"command": "user-hook-after"},
                {"command": "/old/play-intercept prompt"},
            ],
            entries,
        )

    def test_status_card_shows_dossier_restore_command_when_state_was_replaced(self) -> None:
        rendered = _render_status_card(
            {
                "status": "completed",
                "run_id": "recovery-card",
                "selected_harnesses": [],
                "steps": [],
                "backup": {
                    "has_previous_state": True,
                    "restore_command": "play-bootstrap restore --dossier /tmp/run.json",
                },
            }
        )

        self.assertIn("Recovery point", rendered)
        self.assertIn(
            "play-bootstrap restore --dossier /tmp/run.json", rendered
        )

    def test_codex_play_override_removal_preserves_unrelated_toml(self) -> None:
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            'model = "gpt-5"\n\n'
            '[[skills.config]]\npath = "/tmp/play/skills/play/SKILL.md"\n'
            "enabled = false\n\n"
            '[[skills.config]]\nname = "other"\nenabled = false\n\n'
            '[features]\napps = true\n',
            encoding="utf-8",
        )

        step = codex_play_enablement_step()

        updated = config.read_text(encoding="utf-8")
        self.assertEqual("completed", step.status)
        self.assertNotIn("/tmp/play/skills/play/SKILL.md", updated)
        self.assertIn('model = "gpt-5"', updated)
        self.assertIn('name = "other"', updated)
        self.assertIn("[features]\napps = true", updated)

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
        self.assertIn("Congratulations — step 1", rendered)
        self.assertIn("becoming a Playmaster", rendered)
        self.assertIn("Complete the action above", rendered)
        self.assertIn('Codex: codex "\\$play what\'s new"', rendered)
        self.assertIn('Claude Code: claude "/play what\'s new"', rendered)
        self.assertNotIn("run <Play name>", rendered)
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

        self.assertIn("Congratulations — step 1", rendered)
        self.assertIn("becoming a Playmaster", rendered)
        self.assertIn("mind-meld with your agent", rendered)
        self.assertIn("Kimi: start `kimi`, then type `/skill:play what's new`", rendered)
        self.assertIn("Hermes Agent: start `hermes`, then type `/play what's new`", rendered)
        self.assertIn("OpenCode: start `opencode`, then type `/play what's new`", rendered)
        self.assertIn(
            "DeepSeek Harness (preview): start `dsh web`, then type `/play what's new`",
            rendered,
        )

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

        self.assertIn("Status: SETUP PAUSED — SIGN IN REQUIRED", rendered)
        self.assertIn("Codex          WAITING FOR SIGN-IN", rendered)
        self.assertIn("Sign in to finish setup", rendered)
        self.assertIn("choose Google or GitHub", rendered)
        self.assertIn("Play-owned harness state has not been changed", rendered)
        self.assertNotIn("rote login --provider", rendered)
        self.assertNotIn("INCOMPLETE", rendered)

    def test_identity_gate_requires_provider_before_play_mutation(self) -> None:
        runner = MagicMock(
            return_value=MagicMock(returncode=0, stdout="error: Not logged in\n", stderr="")
        )

        step, ready = _identity_gate(
            "/bin/rote", login_provider=None, runner=runner
        )

        self.assertFalse(ready)
        self.assertEqual("onboarding_required", step.status)
        runner.assert_called_once_with(["/bin/rote", "whoami"])

    def test_identity_gate_runs_selected_oauth_provider_and_reverifies(self) -> None:
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(returncode=0, stdout="error: Not logged in\n", stderr=""),
            MagicMock(returncode=0, stdout="browser completed\n", stderr=""),
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
        ]

        step, ready = _identity_gate(
            "/bin/rote", login_provider="github", runner=runner
        )

        self.assertTrue(ready)
        self.assertEqual("completed", step.status)
        self.assertEqual("Signed in with Github as person@example.com.", step.detail)
        self.assertEqual(
            ["/bin/rote", "login", "--provider", "github"], step.command
        )
        self.assertEqual(
            [
                ["/bin/rote", "whoami"],
                ["/bin/rote", "login", "--provider", "github"],
                ["/bin/rote", "whoami"],
            ],
            [call.args[0] for call in runner.call_args_list],
        )

    def test_visible_login_hides_typed_result_but_keeps_browser_guidance(self) -> None:
        stream = StringIO()
        result = _run_login_visible(
            [
                "sh",
                "-c",
                "printf '%s\\n' 'Opening browser...' 'https://example.test/auth' '@@status' 'ok: Login successful' '@@result' 'email: person@example.com'",
            ],
            run,
            stream=stream,
        )

        displayed = stream.getvalue()
        self.assertIn("Opening browser", displayed)
        self.assertIn("https://example.test/auth", displayed)
        self.assertNotIn("@@status", displayed)
        self.assertNotIn("person@example.com", displayed)
        self.assertIn("@@result", result.stdout)

    def test_public_cache_warm_requires_complete_fingerprinted_snapshot(self) -> None:
        runner = MagicMock(
            return_value=MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema": "play.inbox-cache/v1",
                        "refreshed": True,
                        "catalog_complete": True,
                        "catalog_sha256": "sha256:" + "a" * 64,
                        "authority_sha256": "sha256:" + "b" * 64,
                        "baseline_scope": ["modiqo"],
                        "organization_scope": ["modiqo"],
                        "counts": {"public": 47},
                    }
                ),
                stderr="",
            )
        )

        step = _warm_public_play_cache(
            ROOT, runner=runner, progress=Progress(enabled=False)
        )

        self.assertEqual("completed", step.status)
        self.assertIn("47 public Plays", step.detail)
        assert step.command is not None
        self.assertIn("--require-complete-catalog", step.command)
        self.assertEqual("6", step.command[step.command.index("--if-older-than") + 1])

    @patch("scripts.lib.play.bootstrap.backup_play_state")
    @patch("scripts.lib.play.bootstrap.resolve_rote", return_value="/bin/rote")
    def test_apply_stops_before_backup_when_rote_is_too_old(
        self, _resolve_rote: MagicMock, backup: MagicMock
    ) -> None:
        plan = {
            "plan_id": "sha256:rote-version-gate",
            "selected_harnesses": ["codex"],
            "targets": [],
            "rote": {
                "path": "/bin/rote",
                "version": "0.69.1",
                "identity": "authenticated",
                "update": {
                    "status": "current",
                    "detail": "Rote is current.",
                    "recommended_action": "keep",
                },
            },
            "rote_skills": [],
        }
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(returncode=0, stdout="version: 0.69.1\n", stderr=""),
            MagicMock(returncode=0, stdout="version: 0.69.1\n", stderr=""),
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
        ]

        report = apply(
            ROOT,
            requested=["codex"],
            runner=runner,
            run_id="rote-version-gate-run",
            prepared_plan=plan,
        )

        self.assertEqual("blocked", report["status"])
        self.assertEqual(
            ["check_rote_update", "verify_rote_compatibility"],
            [step["id"] for step in report["steps"]],
        )
        self.assertIn("Rote 0.69.1 is too old", report["steps"][-1]["detail"])
        backup.assert_not_called()

    @patch("scripts.lib.play.bootstrap.backup_play_state")
    @patch("scripts.lib.play.bootstrap.resolve_rote", return_value="/bin/rote")
    def test_apply_stops_before_backup_when_identity_is_missing(
        self, _resolve_rote: MagicMock, backup: MagicMock
    ) -> None:
        plan = {
            "plan_id": "sha256:identity-gate",
            "selected_harnesses": ["codex"],
            "targets": [],
            "rote": {
                "path": "/bin/rote",
                "version": "1.0.0",
                "identity": "required",
                "update": {
                    "status": "current",
                    "detail": "Rote is current.",
                    "recommended_action": "keep",
                },
            },
            "rote_skills": [],
        }
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(returncode=0, stdout="version: 1.0.0\n", stderr=""),
            MagicMock(returncode=0, stdout="error: Not logged in\n", stderr=""),
            MagicMock(returncode=0, stdout="version: 1.0.0\n", stderr=""),
            MagicMock(returncode=0, stdout="error: Not logged in\n", stderr=""),
        ]

        report = apply(
            ROOT,
            requested=["codex"],
            runner=runner,
            run_id="identity-gate-run",
            prepared_plan=plan,
        )

        self.assertEqual("onboarding_required", report["status"])
        self.assertEqual(
            ["check_rote_update", "verify_rote_compatibility", "rote_identity"],
            [step["id"] for step in report["steps"]],
        )
        backup.assert_not_called()

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

    def test_status_card_surfaces_stderr_instead_of_a_stdout_heading(self) -> None:
        rendered = _render_status_card(
            {
                "status": "blocked",
                "run_id": "activation-failed",
                "selected_harnesses": ["codex", "claude", "kimi"],
                "steps": [
                    {
                        "id": "install_play",
                        "status": "failed",
                        "detail": (
                            "stdout:\nDetected harnesses: codex, claude, kimi\n\n"
                            "stderr:\ninstall-all: managed Play links are missing"
                        ),
                    }
                ],
            }
        )

        self.assertIn(
            "Install Play: install-all: managed Play links are missing", rendered
        )
        self.assertNotIn("- stdout:", rendered)

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

    @patch("scripts.lib.play.bootstrap.subprocess.run")
    def test_visible_runner_inherits_terminal_output(self, subprocess_run: MagicMock) -> None:
        subprocess_run.return_value = subprocess.CompletedProcess(["bash"], 0)

        result = _run_visible(["bash", "installer.sh"], run)

        subprocess_run.assert_called_once_with(
            ["bash", "installer.sh"],
            text=True,
            check=False,
            timeout=900,
        )
        self.assertEqual("", result.stdout)
        self.assertEqual("", result.stderr)

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
                "Play 0.4.40 is installed and enabled.",
                target="codex",
            )
        ],
    )
    @patch("scripts.lib.play.bootstrap._verify_prompt_intercept")
    @patch("scripts.lib.play.bootstrap.resolve_rote", return_value="/bin/rote")
    def test_apply_existing_rote_updates_converges_installs_hooks_and_verifies(
        self,
        _resolve_rote: MagicMock,
        verify_prompt_intercept: MagicMock,
        _converge_marketplace: MagicMock,
    ) -> None:
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(returncode=0, stdout="version: 1.0.0\n", stderr=""),
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
            MagicMock(returncode=0, stdout="Rote 1.1.0 is available\n", stderr=""),
            MagicMock(returncode=0, stdout="updated to 1.1.0\n", stderr=""),
            MagicMock(returncode=0, stdout="version: 1.1.0\n", stderr=""),
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
            MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema": "play.inbox-cache/v1",
                        "refreshed": True,
                        "catalog_complete": True,
                        "catalog_sha256": "sha256:" + "a" * 64,
                        "authority_sha256": "sha256:" + "b" * 64,
                        "baseline_scope": ["modiqo"],
                        "organization_scope": ["modiqo"],
                        "counts": {"public": 47},
                    }
                ),
                stderr="",
            ),
            MagicMock(returncode=0, stdout="installed all skills\n", stderr=""),
            MagicMock(returncode=0, stdout="Play ready\n", stderr=""),
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
        hook_path = self.home / ".codex" / "hooks.json"
        self.assertTrue(hook_path.is_file())
        installed_hooks = json.loads(hook_path.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(1, len(installed_hooks["UserPromptSubmit"]))
        self.assertIn("play-intercept", json.dumps(installed_hooks["UserPromptSubmit"]))
        step_ids = [step["id"] for step in report["steps"]]
        self.assertLess(
            step_ids.index("verify_play_plugin"), step_ids.index("install_play")
        )
        self.assertLess(
            step_ids.index("verify_rote_compatibility"),
            step_ids.index("rote_identity"),
        )
        self.assertLess(
            step_ids.index("rote_identity"), step_ids.index("backup_play_state")
        )
        self.assertLess(
            step_ids.index("warm_public_play_cache"),
            step_ids.index("backup_play_state"),
        )
        _converge_marketplace.assert_called_once()
        self.assertEqual(
            "0.4.40", _converge_marketplace.call_args.kwargs["expected_version"]
        )
        verify_prompt_intercept.assert_called_once()

    @patch("scripts.lib.play.bootstrap._choose_login_provider", return_value="google")
    @patch("scripts.lib.play.bootstrap._confirm", return_value=True)
    @patch("scripts.lib.play.bootstrap.apply")
    @patch("scripts.lib.play.bootstrap.build_plan")
    def test_guided_install_uses_one_consent_for_plan_and_missing_rote(
        self,
        build: MagicMock,
        apply_plan: MagicMock,
        confirm: MagicMock,
        choose_provider: MagicMock,
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

        output = StringIO()
        with redirect_stdout(output), redirect_stderr(StringIO()):
            result = main(["install", "--harness", "codex", "--run-id", "guided-run"])

        self.assertEqual(0, result)
        confirm.assert_called_once()
        choose_provider.assert_called_once_with()
        self.assertIn("Install Rote and Play", confirm.call_args.args[0])
        self.assertIn("Your setup", output.getvalue())
        self.assertNotIn("Play setup plan", output.getvalue())
        apply_plan.assert_called_once_with(
            ROOT,
            top_k=3,
            requested=["codex"],
            approve_remote_installer=True,
            login_provider="google",
            run_id="guided-run",
            expected_plan_id="sha256:guided",
            prepared_plan=build.return_value,
            progress=ANY,
        )


if __name__ == "__main__":
    unittest.main()
