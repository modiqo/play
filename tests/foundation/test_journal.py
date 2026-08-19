from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from scripts.lib.play.journal import (
    claim_exploration_pulse,
    observe_recall_transition,
    parse_trace,
    recall_summary,
    render_pulse,
    render_recall_summary,
)
from scripts.lib.play.journal_settings import ensure_journal_settings
from scripts.lib.play.private_store import load_json
from scripts.lib.play.sidekick import start_capture


ROOT = Path(__file__).resolve().parents[2]

TRACE = """Trace: play-capture-demo (3 responses, 280ms total, 420 tokens)

  @1 discover      ▓▓░░  40ms  [120]  ✓
  @2 fetch         ▓▓▓░  90ms  [200]  ✗
  @3 fetch         ▓▓▓▓  150ms  [100]  ✓
          edge: @1 [query-read-result] params.owner <- .owner

  ✗ @2: fetch — error (retried as @3)
"""


class ExplorationJournalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = root / "standby.json"
        self.recall_store = root / "recall.json"
        self.settings_store = root / "settings.json"
        self._environment = {
            "PLAY_JOURNAL_SETTINGS_PATH": str(self.settings_store),
            "PLAY_RECALL_JOURNAL_PATH": str(self.recall_store),
        }
        self._saved = {key: os.environ.get(key) for key in self._environment}
        os.environ.update(self._environment)
        self.workspace_path = root / "workspace"
        (self.workspace_path / ".rote").mkdir(parents=True)

        def initialize(_name: str) -> Path:
            return self.workspace_path

        start_capture(
            intent="Compare launch readiness across two sources",
            task_class="creative-exploratory",
            reason="no_match",
            path=self.store,
            workspace_initializer=initialize,
        )

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    @staticmethod
    def analytics(commands: int) -> dict:
        return {
            "stats": {
                "commands": commands,
                "responses": 3,
                "token_savings": {"tokens_saved": 80},
            },
            "trace": parse_trace(TRACE),
        }

    def test_trace_parser_preserves_metadata_dag_and_recovery(self) -> None:
        parsed = parse_trace(TRACE)
        assert parsed is not None
        self.assertEqual(420, parsed["tokens"])
        self.assertEqual(3, len(parsed["bars"]))
        self.assertEqual(
            {"source": 1, "target": 3, "kind": "query-read-result"},
            parsed["edges"][0],
        )
        self.assertEqual(3, parsed["errors"][0]["retry_response_id"])

    @patch.dict(os.environ, {"PLAY_EXPLORATION_PULSE_INTERVAL": "5"})
    def test_pulse_is_claimed_once_after_the_interval(self) -> None:
        reader = lambda _capture: self.analytics(5)
        pulse = claim_exploration_pulse(path=self.store, reader=reader)
        self.assertIsNotNone(pulse)
        self.assertIsNone(claim_exploration_pulse(path=self.store, reader=reader))
        capture = load_json(self.store)["captures"][0]
        self.assertEqual(5, capture["journal"]["last_sequence"])
        self.assertEqual(1, capture["journal"]["pulse_count"])

    @patch.dict(os.environ, {"PLAY_EXPLORATION_PULSE_INTERVAL": "5"})
    def test_below_interval_is_silent_and_does_not_advance_cursor(self) -> None:
        pulse = claim_exploration_pulse(
            path=self.store, reader=lambda _capture: self.analytics(4)
        )
        self.assertIsNone(pulse)
        capture = load_json(self.store)["captures"][0]
        self.assertEqual(0, capture["journal"]["last_sequence"])

    def test_render_is_human_and_does_not_expose_private_capture_state(self) -> None:
        pulse = claim_exploration_pulse(
            path=self.store, reader=lambda _capture: self.analytics(5), force=True
        )
        assert pulse is not None
        text = render_pulse(pulse)
        self.assertIn("Exploration pulse", text)
        self.assertIn("5 new workspace steps", text)
        self.assertIn("280ms operation time", text)
        self.assertIn("@1 → @3", text)
        self.assertIn("recovered at @3", text)
        self.assertNotIn("Compare launch readiness", text)
        self.assertNotIn("cap_", text)
        self.assertNotIn(str(self.workspace_path), text)

    def test_unavailable_analytics_is_silent(self) -> None:
        self.assertIsNone(
            claim_exploration_pulse(path=self.store, reader=lambda _capture: None)
        )

    @patch.dict(os.environ, {"PLAY_EXPLORATION_PULSE_INTERVAL": "5"})
    @patch("scripts.lib.play.journal.read_workspace_trace")
    @patch(
        "scripts.lib.play.journal.read_workspace_stats",
        return_value={"commands": 4},
    )
    def test_expensive_trace_is_skipped_until_the_interval_is_due(
        self, _stats, trace
    ) -> None:
        self.assertIsNone(claim_exploration_pulse(path=self.store))
        trace.assert_not_called()

    def test_second_pulse_is_time_throttled_even_when_more_steps_arrive(self) -> None:
        first = claim_exploration_pulse(
            path=self.store, reader=lambda _capture: self.analytics(5)
        )
        self.assertIsNotNone(first)
        second = claim_exploration_pulse(
            path=self.store, reader=lambda _capture: self.analytics(10)
        )
        self.assertIsNone(second)

    def test_install_settings_enable_both_journals_without_overwriting_opt_out(self) -> None:
        settings, changed = ensure_journal_settings(self.settings_store)
        self.assertTrue(changed)
        self.assertTrue(settings["exploration"]["enabled"])
        self.assertTrue(settings["recall"]["enabled"])
        settings["recall"]["enabled"] = False
        self.settings_store.write_text(json.dumps(settings))

        migrated, changed_again = ensure_journal_settings(self.settings_store)

        self.assertFalse(changed_again)
        self.assertFalse(migrated["recall"]["enabled"])

    def test_recall_events_aggregate_typed_journey_without_prompt_text(self) -> None:
        context = {
            "run_id": "run-1",
            "request": {"original": "secret prompt text"},
            "match": {"reference": "modiqo/retrieve-recent-emails"},
            "inspection": {
                "exact_reference": "modiqo/retrieve-recent-emails@0.2.0"
            },
        }
        transitions = (
            ("classify", "full_match", "use_inspect"),
            ("use_offer", "play_run_approved", "use_prepare"),
            ("use_prepare", "play_run_handoff_ready", "use_run"),
            ("use_receipt", "receipt_ready", "receipt"),
        )
        for source, event, target in transitions:
            observe_recall_transition(
                source=source,
                event=event,
                target=target,
                context=context,
                path=self.recall_store,
            )

        summary = recall_summary(path=self.recall_store)
        self.assertEqual(1, summary["counts"]["matched"])
        self.assertEqual(1, summary["counts"]["approved"])
        self.assertEqual(1, summary["counts"]["run_started"])
        self.assertEqual(1, summary["counts"]["completed"])
        text = render_recall_summary(summary)
        self.assertIn("Play recall journal", text)
        self.assertIn("matched → approved → ran → completed", text)
        self.assertNotIn("secret prompt text", self.recall_store.read_text())

    def test_recall_event_is_deduplicated_by_run_and_stage(self) -> None:
        context = {
            "run_id": "run-repeat",
            "match": {"reference": "modiqo/hello"},
        }
        for _ in range(2):
            observe_recall_transition(
                source="qualify",
                event="exact_play_request",
                target="use_inspect",
                context=context,
                path=self.recall_store,
            )
        self.assertEqual(1, len(load_json(self.recall_store)["events"]))

    def test_search_choice_records_both_the_hit_and_user_selection(self) -> None:
        observe_recall_transition(
            source="search_offer",
            event="search_play_selected",
            target="use_inspect",
            context={
                "run_id": "run-search-choice",
                "match": {"reference": "modiqo/landing-page-assessment"},
            },
            path=self.recall_store,
        )
        summary = recall_summary(path=self.recall_store)
        self.assertEqual(1, summary["counts"]["matched"])
        self.assertEqual(1, summary["counts"]["selected"])

    def test_approved_authentication_block_is_recorded(self) -> None:
        observe_recall_transition(
            source="use_authentication_execute",
            event="authentication_failed",
            target="blocked",
            context={
                "run_id": "run-auth-blocked",
                "inspection": {"exact_reference": "modiqo/search-notion@0.0.2"},
            },
            path=self.recall_store,
        )
        self.assertEqual(1, recall_summary(path=self.recall_store)["counts"]["blocked"])

    def test_recall_store_conforms_to_the_documented_command_log_schema(self) -> None:
        observe_recall_transition(
            source="qualify",
            event="exact_play_request",
            target="use_inspect",
            context={
                "run_id": "run-schema",
                "match": {"reference": "modiqo/hello"},
            },
            path=self.recall_store,
        )
        schema = json.loads(
            (ROOT / "references/controller/command-log.schema.json").read_text()
        )
        Draft202012Validator(schema).validate(load_json(self.recall_store))


if __name__ == "__main__":
    unittest.main()
