from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.intercept import (
    best_match,
    intercept_prompt,
    is_action_request,
    is_cheat_sheet_request,
    is_direct_request,
    load_index,
    settle_nudge,
)
from play.routing import add_route
from play.sidekick import append_ledger_entry, start_capture


FRONTMATTER = """#!/usr/bin/env -S rote play run
/**
 * @rote-frontmatter
 * ---
 * name: {name}
 * version: 1.0.0
 * description: {description}
 * metadata:
 *   discoverability:
 *     tags:
 *       - {tag}
 */
"""


class InterceptTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        base = Path(self._temporary.name)
        self.flows = base / "flows"
        self._environment = {
            "PLAY_INTERCEPT_FLOWS_ROOT": str(self.flows),
            "PLAY_INTERCEPT_INDEX_PATH": str(base / "intercept-index.json"),
            "PLAY_INTERCEPT_STATE_PATH": str(base / "intercept-state.json"),
            "PLAY_INBOX_CACHE_PATH": str(base / "inbox-cache.json"),
            "PLAY_ROUTING_USER_PATH": str(base / "routing.yaml"),
            "PLAY_SIDEKICK_STANDBY_PATH": str(base / "standby.json"),
            "PLAY_SIDEKICK_LEDGER_PATH": str(base / "preferences.json"),
        }
        self._saved = {key: os.environ.get(key) for key in self._environment}
        os.environ.update(self._environment)
        self._write_flow(
            "pr-status-check",
            "Reads a GitHub pull request and reports merge state, checks, and comments.",
            "github",
        )
        self._write_flow(
            "dns-propagation-check",
            "Compares authoritative DNS answers with public resolvers.",
            "dns",
            owner="modiqo",
        )

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._temporary.cleanup()

    @unittest.skipUnless(Path("/usr/bin/python3").is_file(), "system Python unavailable")
    def test_entrypoint_bootstraps_pinned_environment_when_yaml_is_missing(self) -> None:
        if shutil.which("uv") is None:
            self.skipTest("uv unavailable")
        result = subprocess.run(
            [
                "/usr/bin/python3",
                str(ROOT / "scripts" / "bin" / "play-intercept"),
                "prompt",
            ],
            input=json.dumps({"prompt": "play cheat-sheet"}),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
            env={**os.environ, "PLAY_INTERCEPT_UV_BOOTSTRAPPED": "0"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn(
            "cheat-sheet",
            payload["hookSpecificOutput"]["additionalContext"],
        )

    def _write_flow(
        self, name: str, description: str, tag: str, owner: str | None = None
    ) -> None:
        directory = self.flows / owner / name if owner else self.flows / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "main.ts").write_text(
            FRONTMATTER.format(name=name, description=description, tag=tag)
        )

    def test_index_finds_local_and_pulled_flows(self) -> None:
        entries = load_index()
        references = {entry["reference"] for entry in entries}
        self.assertEqual(
            {"pr-status-check", "modiqo/dns-propagation-check"}, references
        )

    def test_index_cache_is_reused_until_flows_change(self) -> None:
        load_index()
        cache_path = Path(os.environ["PLAY_INTERCEPT_INDEX_PATH"])
        first = cache_path.read_text()
        load_index()
        self.assertEqual(first, cache_path.read_text())
        self._write_flow("new-flow", "Something else entirely.", "misc")
        load_index()
        self.assertIn("new-flow", cache_path.read_text())

    def test_specific_match_names_the_play(self) -> None:
        line = intercept_prompt("can you check status on PR 1701 in modiqo/rote")
        assert line is not None
        self.assertIn("pr-status-check", line)
        self.assertIn("play skill", line)

    def test_conversation_is_silent(self) -> None:
        self.assertIsNone(intercept_prompt("why did you pick that module name"))

    def test_catalog_overlap_cannot_activate_play_for_a_design_discussion(self) -> None:
        prompt = "should we use github actions for this repository"
        self.assertFalse(is_action_request(prompt))
        self.assertIsNone(intercept_prompt(prompt))

    def test_play_bound_and_short_prompts_are_silent(self) -> None:
        self.assertIsNone(intercept_prompt("$play settle finished the deploy"))
        self.assertIsNone(intercept_prompt("/play"))
        self.assertIsNone(intercept_prompt("ok"))

    def test_cheat_sheet_command_uses_the_pre_machine_help_path(self) -> None:
        for prompt in (
            "play cheat-sheet",
            "$play cheat sheet",
            "/play cheatsheet",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(is_cheat_sheet_request(prompt))
                line = intercept_prompt(prompt)
                self.assertIsNotNone(line)
                self.assertIn("play-cheat-sheet", line or "")
                self.assertIn("do not enter the Play state machine", line or "")

    def test_routing_management_uses_pre_machine_skill_path(self) -> None:
        project = Path(self._temporary.name) / "routing-project"
        project.mkdir()
        (project / ".git").mkdir()
        add_route(
            project / ".play" / "routing.yaml",
            route_id="github-direct",
            providers=["github"],
            tools=["gh"],
        )

        for prompt in (
            "Initialize Play routing for this repo",
            "remove GitHub from the Play direct route here",
        ):
            with self.subTest(prompt=prompt):
                line = intercept_prompt(prompt, project_path=str(project))
                self.assertIsNotNone(line)
                self.assertIn("pre-machine routing-management path", line or "")
                self.assertIn("Default an unqualified scope to this repository", line or "")

    def test_direct_prefix_is_a_one_turn_hard_bypass(self) -> None:
        for prompt in (
            "direct: check status on PR 1701 in modiqo/rote",
            "without play: check status on PR 1701 in modiqo/rote",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(is_direct_request(prompt))
                self.assertIsNone(intercept_prompt(prompt))
        self.assertFalse(is_direct_request("please work directly on PR 1701"))

    def test_project_direct_route_wins_before_catalog_matching(self) -> None:
        project = Path(self._temporary.name) / "direct-project"
        project.mkdir()
        (project / ".git").mkdir()
        add_route(
            project / ".play" / "routing.yaml",
            route_id="github-direct",
            providers=["github", "github-actions"],
            tools=["git", "gh"],
        )
        prompt = "check github status on PR 1701 in modiqo/rote"
        self.assertTrue(is_action_request(prompt))
        self.assertIsNone(intercept_prompt(prompt, project_path=str(project)))

    def test_ledger_silence_wins_over_a_match(self) -> None:
        append_ledger_entry(
            statement="no plays for status checks",
            task_class="ops-maintenance",
            policy="silent",
        )
        self.assertIsNone(
            intercept_prompt("can you check status on PR 1701 in modiqo/rote")
        )

    def test_project_silence_does_not_escape_its_project(self) -> None:
        project = Path(self._temporary.name) / "quiet-project"
        other = Path(self._temporary.name) / "other-project"
        append_ledger_entry(
            statement="no plays for status checks in this project",
            task_class="ops-maintenance",
            policy="silent",
            scope="project",
            scope_key=str(project),
        )

        prompt = "can you check status on PR 1701 in modiqo/rote"
        self.assertIsNone(intercept_prompt(prompt, project_path=str(project)))
        self.assertIsNotNone(intercept_prompt(prompt, project_path=str(other)))

    def test_session_preference_overrides_global_silence(self) -> None:
        append_ledger_entry(
            statement="no plays for status checks",
            task_class="ops-maintenance",
            policy="silent",
        )
        append_ledger_entry(
            statement="offer plays in this session",
            task_class="ops-maintenance",
            policy="intervene",
            scope="session",
            scope_key="session-open",
        )

        prompt = "can you check status on PR 1701 in modiqo/rote"
        self.assertIsNotNone(intercept_prompt(prompt, session_id="session-open"))
        self.assertIsNone(intercept_prompt(prompt, session_id="session-quiet"))

    def test_generic_advice_fires_once_per_cooldown(self) -> None:
        first = intercept_prompt("export the quarterly numbers into a spreadsheet")
        assert first is not None
        self.assertIn("search", first)
        self.assertIsNone(
            intercept_prompt("export the quarterly numbers into a spreadsheet")
        )

    def test_no_match_no_verb_is_silent(self) -> None:
        self.assertIsNone(intercept_prompt("refactor the widget renderer for clarity"))

    def test_settle_nudge_fires_once_per_capture_and_session(self) -> None:
        def initialize(name: str) -> Path:
            path = Path(self._temporary.name) / name
            path.mkdir()
            return path

        capture = start_capture(
            intent="deploy staging and post summary",
            task_class="build-ship-chore",
            reason="no_match",
            workspace_initializer=initialize,
        )
        first = settle_nudge("session-a")
        assert first is not None
        self.assertIn("$play settle", first)
        self.assertIn(capture["reference"], first)
        self.assertIsNone(settle_nudge("session-a"))
        self.assertIsNotNone(settle_nudge("session-b"))

    def test_settle_nudge_silent_without_a_hook(self) -> None:
        self.assertIsNone(settle_nudge("session-a"))

    def test_best_match_requires_two_name_tokens(self) -> None:
        entries = load_index()
        self.assertIsNone(
            best_match("compares answers with public things somehow", entries)
        )
        # A single shared word ("check") in a meta-prompt must not clear the bar.
        self.assertIsNone(
            best_match(
                "go ahead and check that everything reports its state correctly",
                entries,
            )
        )

    def test_specific_match_survives_the_two_token_bar(self) -> None:
        entries = load_index()
        match = best_match("can you check status on PR 1701", entries)
        assert match is not None
        self.assertEqual("pr-status-check", match["reference"])

    def test_hub_catalog_entries_match_when_not_local(self) -> None:
        from play.private_store import atomic_write_json

        atomic_write_json(
            Path(os.environ["PLAY_INBOX_CACHE_PATH"]),
            {
                "schema": "play.inbox-cache/v1",
                "fetched_at": "2026-08-11T00:00:00+00:00",
                "window_days": 7,
                "summary_line": None,
                "counts": {"new": 0, "revised": 0},
                "digest": {},
                "markdown": None,
                "catalog": [
                    {
                        "reference": "modiqo/list-top-committers",
                        "name": "list-top-committers",
                        "description": "Lists top contributors for a GitHub repository.",
                        "visibility": "public",
                    }
                ],
            },
        )
        line = intercept_prompt("list top committers for modiqo/rote")
        assert line is not None
        self.assertIn("available in your hub", line)
        self.assertIn("modiqo/list-top-committers", line)
        self.assertIn("inspects first", line)
        self.assertIn("never pull plays or adapters manually", line)


if __name__ == "__main__":
    unittest.main()
