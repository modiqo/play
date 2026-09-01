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
    is_bare_hello_request,
    load_index,
    milestone_nudge,
    settle_nudge,
)
from play.milestones import record_event
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
            "PLAY_MILESTONE_PATH": str(base / "milestones.json"),
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
            input=json.dumps({"prompt": "check status on PR 1701"}),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
            env={**os.environ, "PLAY_INTERCEPT_UV_BOOTSTRAPPED": "0"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn(
            "pr-status-check",
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

    def test_index_ignores_nonreplayable_typescript(self) -> None:
        directory = self.flows / "not-a-play"
        directory.mkdir(parents=True)
        (directory / "main.ts").write_text("export const value = 1;\n")

        references = {entry["reference"] for entry in load_index()}

        self.assertNotIn("not-a-play", references)

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
        self.assertIn("high-confidence match", line)
        self.assertIn("non-blocking", line)
        self.assertIn("change the original request", line)

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

    def test_plain_play_prefix_is_not_interpreted_by_discovery(self) -> None:
        for prompt in ("play", "play run hello", "Play run weekly-report"):
            with self.subTest(prompt=prompt):
                self.assertIsNone(intercept_prompt(prompt))

    def test_bare_hello_stays_on_the_normal_agent_route(self) -> None:
        self._write_flow(
            "hello",
            "Checks public service status and reports what is available.",
            "status",
            owner="modiqo",
        )
        for prompt in ("run hello", "Run the Hello Play", "please run hello."):
            with self.subTest(prompt=prompt):
                self.assertTrue(is_bare_hello_request(prompt))
                self.assertIsNone(intercept_prompt(prompt))

    def test_cheat_sheet_command_is_left_to_explicit_skill_invocation(self) -> None:
        for prompt in (
            "play cheat-sheet",
            "$play cheat sheet",
            "/play cheatsheet",
            "/skill:play cheat-sheet",
        ):
            with self.subTest(prompt=prompt):
                self.assertIsNone(intercept_prompt(prompt))

    def test_journal_command_is_left_to_explicit_skill_invocation(self) -> None:
        for prompt in (
            "$play journal",
            "play recall journal yesterday",
            "show me my Play journal 2026-08-17",
        ):
            with self.subTest(prompt=prompt):
                self.assertIsNone(intercept_prompt(prompt))

    def test_whats_new_command_is_left_to_explicit_skill_invocation(self) -> None:
        for prompt in (
            "play what's new",
            "$play whats new",
            "/play what's new",
            "/skill:play what's new",
            "popular Plays",
            "trending Plays",
        ):
            with self.subTest(prompt=prompt):
                self.assertIsNone(intercept_prompt(prompt))

    def test_routing_management_is_left_to_explicit_skill_invocation(self) -> None:
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
                self.assertIsNone(intercept_prompt(prompt, project_path=str(project)))

    def test_direct_prefix_is_not_interpreted_by_the_discovery_hook(self) -> None:
        for prompt in (
            "direct: check status on PR 1701 in modiqo/rote",
            "without play: check status on PR 1701 in modiqo/rote",
        ):
            with self.subTest(prompt=prompt):
                self.assertIsNone(intercept_prompt(prompt))

    def test_project_direct_route_does_not_replace_discovery_matching(self) -> None:
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
        line = intercept_prompt(prompt, project_path=str(project))
        self.assertIsNotNone(line)
        self.assertIn("pr-status-check", line or "")
        self.assertNotIn("Validated direct route", line or "")

    def test_discovery_does_not_read_global_play_preferences(self) -> None:
        append_ledger_entry(
            statement="no plays for status checks",
            task_class="ops-maintenance",
            policy="silent",
        )
        self.assertIsNotNone(
            intercept_prompt("can you check status on PR 1701 in modiqo/rote")
        )

    def test_discovery_does_not_read_project_play_preferences(self) -> None:
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
        self.assertIsNotNone(intercept_prompt(prompt, project_path=str(project)))
        self.assertIsNotNone(intercept_prompt(prompt, project_path=str(other)))

    def test_discovery_does_not_read_session_play_preferences(self) -> None:
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
        self.assertIsNotNone(intercept_prompt(prompt, session_id="session-quiet"))

    def test_no_match_is_always_silent(self) -> None:
        prompt = "export the quarterly numbers into a spreadsheet"
        self.assertIsNone(intercept_prompt(prompt))
        self.assertIsNone(intercept_prompt(prompt))

    def test_play_and_rote_complaint_does_not_trigger_discovery(self) -> None:
        from play.private_store import atomic_write_json

        atomic_write_json(
            Path(os.environ["PLAY_INBOX_CACHE_PATH"]),
            {
                "schema": "play.inbox-cache/v1",
                "catalog_complete": True,
                "public_catalog": [
                    {
                        "reference": "modiqo/process-only-play-run-verification",
                        "name": "process-only-play-run-verification",
                        "description": "Verifies Play and Rote process state.",
                        "visibility": "public",
                        "tags": ["play", "rote", "session", "state"],
                    }
                ],
            },
        )

        prompt = (
            "review the current play code as one user is complaining that their "
            "session state is always intercepted with plays/rote"
        )

        self.assertIsNone(intercept_prompt(prompt))

    def test_generic_catalog_tags_cannot_count_as_name_hits(self) -> None:
        from play.private_store import atomic_write_json

        atomic_write_json(
            Path(os.environ["PLAY_INBOX_CACHE_PATH"]),
            {
                "schema": "play.inbox-cache/v1",
                "catalog_complete": True,
                "public_catalog": [
                    {
                        "reference": "modiqo/archive-records",
                        "name": "archive-records",
                        "description": "Archives records after a verified request.",
                        "visibility": "public",
                        "tags": ["play", "rote", "session", "state"],
                    }
                ],
            },
        )

        self.assertIsNone(intercept_prompt("review the Play and Rote session state"))

    def test_possible_match_does_not_interrupt_ordinary_work(self) -> None:
        prompt = "review PR comments before merge"
        self.assertIsNone(intercept_prompt(prompt))

    def test_no_match_no_verb_is_silent(self) -> None:
        self.assertIsNone(intercept_prompt("refactor the widget renderer for clarity"))

    def test_active_capture_stays_internal_at_stop(self) -> None:
        def initialize(name: str) -> Path:
            path = Path(self._temporary.name) / name
            path.mkdir()
            return path

        start_capture(
            intent="deploy staging and post summary",
            task_class="build-ship-chore",
            reason="no_match",
            workspace_initializer=initialize,
        )
        self.assertIsNone(milestone_nudge("session-a"))
        self.assertIsNone(settle_nudge("session-b"))

    def test_first_run_unlock_teaches_playrunner_to_playmaker_path_once(self) -> None:
        record_event(
            "play_run_completed",
            run_id="run-hello",
            reference="modiqo/hello",
        )

        first = milestone_nudge("session-a")
        assert first is not None
        self.assertIn("Playrunner unlocked", first)
        self.assertIn("$play <play URI>", first)
        self.assertIn("$play <what you want in English>", first)
        self.assertIn("$play explore <something useful>", first)
        self.assertIn("save this Play", first)
        self.assertNotIn("cap_", first)
        self.assertNotIn("$play settle", first)
        self.assertIsNone(milestone_nudge("session-a"))
        self.assertIsNone(milestone_nudge("session-b"))

        record_event(
            "play_run_completed",
            run_id="run-recent-emails",
            reference="modiqo/retrieve-recent-emails",
        )
        follow_up = milestone_nudge("session-b")
        assert follow_up is not None
        self.assertIn("Play complete", follow_up)
        self.assertIn("modiqo/retrieve-recent-emails", follow_up)
        self.assertNotIn("Playrunner unlocked", follow_up)

    def test_milestone_nudge_silent_without_an_event(self) -> None:
        self.assertIsNone(settle_nudge("session-a"))

    def test_legacy_stop_command_is_an_inert_compatibility_noop(self) -> None:
        record_event(
            "play_run_completed",
            run_id="run-legacy-stop",
            reference="modiqo/hello",
        )

        result = subprocess.run(
            [str(ROOT / "scripts" / "bin" / "play-intercept"), "milestone-nudge"],
            input=json.dumps({"session_id": "session-a"}),
            text=True,
            capture_output=True,
            check=False,
            env=os.environ.copy(),
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)

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
                "catalog_complete": True,
                "public_catalog": [
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
        self.assertIn("high-confidence match", line)
        self.assertIn("modiqo/list-top-committers", line)
        self.assertIn("explicitly invoke Play", line)
        self.assertIn("load Play or Rote state", line)

    def test_automatic_hook_ignores_private_rows_from_an_unverifiable_cache(self) -> None:
        from play.private_store import atomic_write_json

        atomic_write_json(
            Path(os.environ["PLAY_INBOX_CACHE_PATH"]),
            {
                "schema": "play.inbox-cache/v1",
                "catalog": [
                    {
                        "reference": "former-org/private-report",
                        "name": "private-report",
                        "description": "Builds a private report from internal data.",
                        "visibility": "private",
                    }
                ],
            },
        )

        self.assertIsNone(intercept_prompt("build private report from internal data"))

    def test_automatic_hook_ignores_public_rows_from_an_incomplete_cache(self) -> None:
        from play.private_store import atomic_write_json

        atomic_write_json(
            Path(os.environ["PLAY_INBOX_CACHE_PATH"]),
            {
                "schema": "play.inbox-cache/v1",
                "public_catalog": [
                    {
                        "reference": "modiqo/list-top-committers",
                        "name": "list-top-committers",
                        "description": "Lists top contributors for a GitHub repository.",
                        "visibility": "public",
                    }
                ],
            },
        )

        self.assertIsNone(intercept_prompt("list top committers for modiqo/rote"))

    def test_unpublished_local_play_precedes_same_named_catalog_play(self) -> None:
        from play.private_store import atomic_write_json

        atomic_write_json(
            Path(os.environ["PLAY_INBOX_CACHE_PATH"]),
            {
                "schema": "play.inbox-cache/v1",
                "catalog_complete": True,
                "public_catalog": [
                    {
                        "reference": "modiqo/pr-status-check",
                        "name": "pr-status-check",
                        "description": "Remote PR status checker.",
                        "visibility": "public",
                        "catalog_tier": "public_baseline",
                    }
                ],
            },
        )

        line = intercept_prompt("check status on PR 1701")

        assert line is not None
        self.assertIn("high-confidence match `pr-status-check`", line)
        self.assertNotIn("modiqo/pr-status-check", line)

    def test_followup_adverb_does_not_silence_cached_rideshare_match(self) -> None:
        from play.private_store import atomic_write_json

        atomic_write_json(
            Path(os.environ["PLAY_INBOX_CACHE_PATH"]),
            {
                "schema": "play.inbox-cache/v1",
                "catalog_complete": True,
                "public_catalog": [
                    {
                        "reference": "modiqo/retrieve-rideshare-receipts",
                        "name": "retrieve-rideshare-receipts",
                        "description": "Retrieves Uber, Lyft, and Waymo receipts from email.",
                        "visibility": "public",
                    }
                ],
            },
        )

        prompt = "can you now retrieve rideshare receipts"
        self.assertTrue(is_action_request(prompt))
        line = intercept_prompt(prompt)
        assert line is not None
        self.assertIn("modiqo/retrieve-rideshare-receipts", line)

    def test_request_prefix_recovers_typo_from_cached_play_name(self) -> None:
        from play.private_store import atomic_write_json

        atomic_write_json(
            Path(os.environ["PLAY_INBOX_CACHE_PATH"]),
            {
                "schema": "play.inbox-cache/v1",
                "catalog_complete": True,
                "public_catalog": [
                    {
                        "reference": "modiqo/retrieve-recent-emails",
                        "name": "retrieve-recent-emails",
                        "description": "Retrieves recent messages from Gmail.",
                        "visibility": "public",
                    }
                ],
            },
        )

        prompt = "can you reti" + "eve recent emails"
        self.assertFalse(is_action_request(prompt))
        line = intercept_prompt(prompt)
        assert line is not None
        self.assertIn("modiqo/retrieve-recent-emails", line)
        self.assertIn("high-confidence match", line)

    def test_prefixed_discussion_stays_silent_with_strong_catalog_overlap(self) -> None:
        from play.private_store import atomic_write_json

        atomic_write_json(
            Path(os.environ["PLAY_INBOX_CACHE_PATH"]),
            {
                "schema": "play.inbox-cache/v1",
                "catalog_complete": True,
                "public_catalog": [
                    {
                        "reference": "modiqo/retrieve-recent-emails",
                        "name": "retrieve-recent-emails",
                        "description": "Retrieves recent messages from Gmail.",
                        "visibility": "public",
                    }
                ],
            },
        )

        self.assertIsNone(
            intercept_prompt("can you explain retrieve recent emails")
        )

    def test_current_hub_namespace_wins_over_stale_local_owner(self) -> None:
        from play.private_store import atomic_write_json

        self._write_flow(
            "retrieve-rideshare-receipts",
            "Old locally pulled rideshare receipt workflow.",
            "receipts",
            owner="workplace-automation",
        )
        atomic_write_json(
            Path(os.environ["PLAY_INBOX_CACHE_PATH"]),
            {
                "schema": "play.inbox-cache/v1",
                "catalog_complete": True,
                "public_catalog": [
                    {
                        "reference": "modiqo/retrieve-rideshare-receipts",
                        "name": "retrieve-rideshare-receipts",
                        "description": "Current rideshare receipt Play.",
                        "visibility": "public",
                    }
                ],
            },
        )

        line = intercept_prompt("can you now retrieve rideshare receipts")
        assert line is not None
        self.assertIn("modiqo/retrieve-rideshare-receipts", line)
        self.assertNotIn("workplace-automation", line)


if __name__ == "__main__":
    unittest.main()
