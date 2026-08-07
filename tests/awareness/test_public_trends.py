from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.public_trends import (
    PublicStatsBatch,
    PublicStatsError,
    build_public_trends,
    fetch_public_stats,
    fetch_public_stats_parallel,
    render_markdown,
)


def card(reference: str, *, downloads: int = 1, installs: int = 0, kind: str = "org") -> dict:
    owner, versioned_name = reference.split("/", 1)
    name, _, version = versioned_name.partition("@")
    resolved = reference if version else f"{reference}@1.0.0"
    return {
        "schema": "rote.play.v1",
        "reference": resolved,
        "name": name,
        "title": name.replace("-", " ").title(),
        "owner": {"slug": owner, "kind": kind},
        "description": f"The {name} Play.",
        "visibility": "public",
        "version": version or "1.0.0",
        "stats": {"downloads": downloads, "installs": installs},
    }


class PublicTrendsTest(unittest.TestCase):
    @patch("play.public_trends.run_json")
    def test_fetch_uses_exact_public_json_card_without_redirects(self, run_json) -> None:
        run_json.return_value = card("modiqo/hello@0.1.0", downloads=8, installs=3)
        result = fetch_public_stats("modiqo/hello@0.1.0")
        command = run_json.call_args.args[0]
        self.assertEqual("curl", command[0])
        self.assertIn("--max-redirs", command)
        self.assertIn("Accept: application/json", command)
        self.assertEqual(
            "https://play.modiqo.ai/modiqo/hello@0.1.0.json",
            command[-1],
        )
        self.assertEqual(8, result["download_count"])
        self.assertEqual(3, result["install_count"])
        self.assertIsInstance(result["fetch_latency_ms"], float)

    @patch("play.public_trends.fetch_public_stats")
    def test_batch_fetches_stats_in_parallel_and_returns_stable_order(self, fetch) -> None:
        lock = threading.Lock()
        active = 0
        maximum_active = 0

        def delayed(reference: str) -> dict:
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return {
                **card(reference),
                "reference": f"{reference}@1.0.0",
                "exact_reference": f"{reference}@1.0.0",
                "base_reference": reference,
                "owner": reference.split("/", 1)[0],
                "owner_kind": "org",
                "download_count": 1,
                "install_count": 0,
            }

        fetch.side_effect = delayed
        batch = fetch_public_stats_parallel(
            ["beta/two", "alpha/one", "gamma/three"],
            max_workers=3,
        )
        self.assertGreater(maximum_active, 1)
        self.assertEqual(
            ["alpha/one", "beta/two", "gamma/three"],
            [play["base_reference"] for play in batch.plays],
        )
        self.assertEqual(3, batch.workers)
        self.assertGreater(batch.elapsed_ms, 0)

    @patch("play.public_trends.run_json")
    def test_private_or_missing_stats_fail_closed(self, run_json) -> None:
        private = card("alpha/hidden")
        private["visibility"] = "private"
        run_json.return_value = private
        with self.assertRaisesRegex(PublicStatsError, "is not public"):
            fetch_public_stats("alpha/hidden")

    def test_report_groups_owner_kinds_and_does_not_call_totals_trending(self) -> None:
        plays = [
            {
                "reference": "alice/one@1.0.0",
                "owner": "alice",
                "owner_kind": "user",
                "title": "One",
                "download_count": 2,
                "install_count": 1,
            },
            {
                "reference": "modiqo/hello@0.1.0",
                "owner": "modiqo",
                "owner_kind": "org",
                "title": "Hello",
                "download_count": 9,
                "install_count": 4,
            },
        ]
        report = build_public_trends(PublicStatsBatch(plays, [], 2, 0, 12.5, 2))
        self.assertEqual("cumulative_snapshot", report["metric_kind"])
        self.assertEqual("unavailable", report["trend_status"])
        self.assertEqual(["alice", "modiqo"], [group["owner"] for group in report["groups"]])
        rendered = render_markdown(report)
        self.assertIn("9 downloads · 4 installs", rendered)
        self.assertIn("These totals are not a time-window trend.", rendered)


if __name__ == "__main__":
    unittest.main()
