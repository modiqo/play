from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.lib.play.journey_model_telemetry import (
    ensure_model_assets,
    context_limits_for,
    interaction_cost,
    load_catalog,
    load_model_config,
    pricing_for,
    select_model,
    summarize,
    telemetry_context,
)


class JourneyModelTelemetryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / ".play"
        self.workspace = self.root / "workspace"
        rote = self.workspace / ".rote"
        rote.mkdir(parents=True)
        connection = sqlite3.connect(rote / "workspace.db")
        connection.execute("CREATE TABLE workspace_meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute(
            "INSERT INTO workspace_meta (key, value) VALUES (?, ?)",
            (
                "exploration_model",
                json.dumps({"provider": "openai", "model": "gpt-5", "captured_at": "2026-08-20T00:00:00Z"}),
            ),
        )
        connection.commit()
        connection.close()
        ensure_model_assets(home=self.home)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_workspace_identity_wins_and_config_supplies_effort(self) -> None:
        config = load_model_config(home=self.home)
        model = select_model(self.workspace, config)
        self.assertEqual("gpt-5", model["name"])
        self.assertEqual("gpt-5", model["family"])
        self.assertEqual("medium", model["effort"])
        self.assertEqual("rote_workspace", model["source"])
        pricing = pricing_for(model, load_catalog(config, home=self.home))
        self.assertIsNotNone(pricing)
        assert pricing is not None
        self.assertEqual("gpt-5", pricing["key"])
        cost = interaction_cost(100, 100, pricing)
        self.assertIsNotNone(cost)
        assert cost is not None
        self.assertAlmostEqual(0.001125, cost)
        limits = context_limits_for(model, load_catalog(config, home=self.home), config)
        self.assertIsNotNone(limits)
        assert limits is not None
        self.assertEqual(272_000, limits["window_tokens"])
        self.assertEqual(244_800, limits["compaction_at_tokens"])
        self.assertEqual("estimated_from_captured_io", limits["kind"])

    def test_context_prices_each_record_and_summarizes_outcomes(self) -> None:
        records = [
            {"input_tokens": 100, "output_tokens": 10, "status": "succeeded"},
            {"input_tokens": 20, "output_tokens": 5, "status": "failed"},
        ]
        context = telemetry_context(self.workspace, records, home=self.home)
        self.assertEqual("captured_tool_io", context["scope"])
        self.assertTrue(all(record["estimated_cost_usd"] > 0 for record in records))
        self.assertEqual(272_000, context["context"]["window_tokens"])
        summary = summarize(records)
        self.assertEqual(
            {"input_tokens": 120, "output_tokens": 15, "count": 2, "success": 1, "error": 1},
            {key: summary[key] for key in ("input_tokens", "output_tokens", "count", "success", "error")},
        )

    def test_default_model_supports_a_packaged_journey_without_a_workspace(self) -> None:
        records = [{"input_tokens": 62, "output_tokens": 38, "status": "succeeded"}]
        context = telemetry_context(None, records, home=self.home)

        self.assertEqual("codex", context["model"]["name"])
        self.assertEqual("play_default", context["model"]["source"])
        self.assertEqual(100, context["session"]["input_tokens"] + context["session"]["output_tokens"])
        self.assertIsNotNone(context["pricing"])
        self.assertIsNotNone(context["context"])


if __name__ == "__main__":
    unittest.main()
