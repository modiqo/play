from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.registry import inspect_authorized_public_flows, inspect_play, load_authorized_flows


class RegistryTest(unittest.TestCase):
    @patch("play.registry.run_rote_json")
    def test_authorized_flow_reads_are_scoped_per_organization(self, run_json) -> None:
        def payload(*arguments, **_kwargs):
            slug = arguments[4]
            return [
                {
                    "name": f"{slug}-play",
                    "description": "Scoped",
                    "visibility": "private",
                    "created_at": "2026-08-01T00:00:00+00:00",
                    "updated_at": "2026-08-01T00:00:00+00:00",
                }
            ]

        run_json.side_effect = payload
        grouped = load_authorized_flows({"beta", "alpha"})
        self.assertEqual(["alpha", "beta"], list(grouped))
        self.assertEqual("alpha-play", grouped["alpha"][0]["name"])
        self.assertEqual(2, run_json.call_count)

    @patch("play.registry.run_rote_json")
    def test_play_inspect_normalizes_metrics_and_parameter_defaults(self, run_json) -> None:
        run_json.return_value = {
            "schema": 1,
            "ok": True,
            "data": {
                "play_inspect": {
                    "identity": {
                        "owner": "alpha",
                        "name": "report",
                        "description": "Report",
                        "visibility": "public",
                        "version": "1.2.0",
                    },
                    "archive": {"download_count": 8, "install_count": 3},
                    "execution": {"play_run_eligible": True},
                    "parameters": [
                        {"name": "days", "type": "string", "default": "7"},
                        {"name": "required", "type": "string"},
                    ],
                }
            },
        }
        flow = inspect_play("alpha/report")
        self.assertEqual("alpha/report", flow["reference"])
        self.assertEqual("alpha/report@1.2.0", flow["exact_reference"])
        self.assertEqual(8, flow["download_count"])
        self.assertEqual({"days": "7"}, flow["default_parameters"])

    @patch("play.registry.inspect_play")
    def test_public_inspection_is_bounded_to_authorized_public_candidates(self, inspect) -> None:
        inspect.return_value = {
            "reference": "alpha/public",
            "exact_reference": "alpha/public@1.0.0",
            "name": "public",
            "owner": "alpha",
            "description": "",
            "visibility": "public",
            "version": "1.0.0",
            "download_count": 2,
            "install_count": 1,
            "play_run_eligible": True,
            "default_parameters": {},
        }
        batch = inspect_authorized_public_flows(
            {
                "alpha": [
                    {"name": "public", "visibility": "public"},
                    {"name": "private", "visibility": "private"},
                ]
            }
        )
        inspect.assert_called_once_with("alpha/public")
        self.assertEqual([], batch.errors)
        self.assertEqual("alpha/public", batch.flows[0][1]["reference"])
        self.assertEqual(1, batch.candidate_count)
        self.assertEqual(0, batch.omitted_count)

    @patch("play.registry.inspect_play")
    def test_public_inspection_budget_prefers_recent_candidates(self, inspect) -> None:
        def inspected(reference: str):
            owner, name = reference.split("/", 1)
            return {
                "reference": reference,
                "exact_reference": f"{reference}@1.0.0",
                "name": name,
                "owner": owner,
                "description": "",
                "visibility": "public",
                "version": "1.0.0",
                "download_count": 1,
                "install_count": 0,
                "play_run_eligible": True,
                "default_parameters": {},
            }

        inspect.side_effect = inspected
        batch = inspect_authorized_public_flows(
            {
                "alpha": [
                    {
                        "name": "older",
                        "visibility": "public",
                        "updated_at": "2026-08-01T00:00:00Z",
                    },
                    {
                        "name": "newer",
                        "visibility": "public",
                        "updated_at": "2026-08-03T00:00:00Z",
                    },
                ]
            },
            limit=1,
        )
        inspect.assert_called_once_with("alpha/newer")
        self.assertEqual(2, batch.candidate_count)
        self.assertEqual(1, batch.omitted_count)


if __name__ == "__main__":
    unittest.main()
