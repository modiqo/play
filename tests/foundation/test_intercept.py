from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.intercept import best_match, intercept_prompt, load_index, settle_nudge
from play.sidekick import append_ledger_entry, arm_hook


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

    def test_play_bound_and_short_prompts_are_silent(self) -> None:
        self.assertIsNone(intercept_prompt("$play settle finished the deploy"))
        self.assertIsNone(intercept_prompt("/play"))
        self.assertIsNone(intercept_prompt("ok"))

    def test_ledger_silence_wins_over_a_match(self) -> None:
        append_ledger_entry(
            statement="no plays for status checks",
            task_class="ops-maintenance",
            policy="silent",
        )
        self.assertIsNone(
            intercept_prompt("can you check status on PR 1701 in modiqo/rote")
        )

    def test_generic_advice_fires_once_per_cooldown(self) -> None:
        first = intercept_prompt("export the quarterly numbers into a spreadsheet")
        assert first is not None
        self.assertIn("search", first)
        self.assertIsNone(
            intercept_prompt("export the quarterly numbers into a spreadsheet")
        )

    def test_no_match_no_verb_is_silent(self) -> None:
        self.assertIsNone(intercept_prompt("refactor the widget renderer for clarity"))

    def test_settle_nudge_fires_once_per_hook_and_session(self) -> None:
        arm_hook(intent="deploy staging and post summary", task_class="build-ship-chore", reason="no_match")
        first = settle_nudge("session-a")
        assert first is not None
        self.assertIn("$play settle", first)
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


if __name__ == "__main__":
    unittest.main()
