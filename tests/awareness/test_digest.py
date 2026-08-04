from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.digest import build_digest, classify_updates, rank_public, render_markdown
from play.registry import Organization


class DigestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 8, 3, tzinfo=timezone.utc)
        self.end = datetime(2026, 8, 4, tzinfo=timezone.utc)

    def test_classifies_new_and_revised_without_crossing_org_boundaries(self) -> None:
        grouped = {
            "alpha": [
                {
                    "name": "new-play",
                    "visibility": "private",
                    "created_at": "2026-08-03T04:00:00+00:00",
                    "updated_at": "2026-08-03T04:00:00+00:00",
                    "default_parameters": {"days": 7},
                },
                {
                    "name": "revised-play",
                    "visibility": "public",
                    "created_at": "2026-07-01T04:00:00+00:00",
                    "latest_version_created_at": "2026-08-03T06:00:00+00:00",
                    "updated_at": "2026-08-03T06:00:00+00:00",
                },
            ]
        }
        new, revised = classify_updates(grouped, self.start, self.end)
        self.assertEqual(["alpha/new-play"], [item["reference"] for item in new])
        self.assertEqual(["alpha/revised-play"], [item["reference"] for item in revised])
        self.assertEqual("private", new[0]["visibility"])
        self.assertEqual({"days": 7}, new[0]["parameters"])

    def test_public_ranking_is_labeled_as_lifetime_downloads(self) -> None:
        public = [
            ("beta", {"name": "second", "visibility": "public", "download_count": 2}),
            ("alpha", {"name": "first", "visibility": "public", "download_count": 8}),
            ("private", {"name": "hidden", "visibility": "private", "download_count": 99}),
        ]
        ranked, contract = rank_public(public, 5)
        self.assertEqual(["alpha/first", "beta/second"], [item["reference"] for item in ranked])
        self.assertEqual("lifetime_downloads", contract["metric"])
        self.assertNotIn("trending", contract["label"].casefold())
        self.assertTrue(all(item["visibility"] == "public" for item in ranked))
        self.assertTrue(all(item["parameters"] == {} for item in ranked))

    def test_digest_reports_personal_stats_as_unavailable_not_zero(self) -> None:
        digest = build_digest(
            [Organization("alpha", "Alpha")],
            {"alpha": []},
            [],
            start=self.start,
            end=self.end,
            public_limit=5,
        )
        self.assertEqual("unavailable", digest["personal_stats"]["status"])
        self.assertTrue(digest["ranking"]["complete"])
        self.assertEqual("unavailable", digest["ranking"]["global_status"])
        self.assertEqual("play.digest-checkpoint/v1", digest["next_checkpoint"]["schema"])

    def test_updated_at_alone_does_not_claim_a_released_revision(self) -> None:
        grouped = {
            "alpha": [
                {
                    "name": "metadata-only",
                    "visibility": "public",
                    "created_at": "2026-07-01T00:00:00+00:00",
                    "updated_at": "2026-08-03T10:00:00+00:00",
                }
            ]
        }
        new, revised = classify_updates(grouped, self.start, self.end)
        self.assertEqual([], new)
        self.assertEqual([], revised)
        digest = build_digest(
            [Organization("alpha", "Alpha")],
            grouped,
            [],
            start=self.start,
            end=self.end,
            public_limit=5,
        )
        self.assertFalse(digest["org_updates"]["revised_complete"])
        self.assertIn("Revised in your organizations", render_markdown(digest))
        self.assertIn("released-version timestamps", render_markdown(digest))

    def test_inspected_update_is_version_pinned_and_actionable(self) -> None:
        grouped = {
            "alpha": [
                {
                    "name": "new-play",
                    "visibility": "private",
                    "created_at": "2026-08-03T04:00:00+00:00",
                    "updated_at": "2026-08-03T04:00:00+00:00",
                }
            ]
        }
        digest = build_digest(
            [Organization("alpha", "Alpha")],
            grouped,
            [],
            start=self.start,
            end=self.end,
            public_limit=5,
            update_inspections={
                "alpha/new-play": {
                    "reference": "alpha/new-play",
                    "exact_reference": "alpha/new-play@1.1.0",
                    "version": "1.1.0",
                    "default_parameters": {"days": "7"},
                }
            },
        )
        item = digest["org_updates"]["new"][0]
        self.assertTrue(item["actionable"])
        self.assertEqual("alpha/new-play@1.1.0", item["reference"])
        self.assertEqual({"days": "7"}, item["parameters"])

    def test_ranking_reports_partial_inspection_without_inventing_global_coverage(self) -> None:
        ranked, contract = rank_public(
            [("alpha", {"name": "one", "visibility": "public", "download_count": 3})],
            5,
            source_complete=False,
            source_errors=["beta/two: inspect timed out"],
            candidate_count=2,
            omitted_count=1,
        )
        self.assertEqual(["alpha/one"], [item["reference"] for item in ranked])
        self.assertFalse(contract["complete"])
        self.assertEqual("authorized_organizations", contract["scope"])
        self.assertEqual("unavailable", contract["global_status"])
        self.assertEqual(1, contract["omitted_count"])

    def test_awareness_sha_is_stable_across_windows_but_changes_with_source_state(self) -> None:
        grouped = {
            "alpha": [
                {
                    "name": "one",
                    "visibility": "private",
                    "created_at": "2026-07-01T00:00:00+00:00",
                    "latest_version_created_at": "2026-07-01T00:00:00+00:00",
                }
            ]
        }
        first = build_digest(
            [Organization("alpha", "Alpha")],
            grouped,
            [],
            start=self.start,
            end=self.end,
            public_limit=5,
        )
        later = build_digest(
            [Organization("alpha", "Alpha")],
            grouped,
            [],
            start=self.end,
            end=datetime(2026, 8, 5, tzinfo=timezone.utc),
            public_limit=5,
        )
        self.assertEqual(first["awareness_sha"], later["awareness_sha"])

        changed = {"alpha": [{**grouped["alpha"][0], "visibility": "public"}]}
        revised = build_digest(
            [Organization("alpha", "Alpha")],
            changed,
            [],
            start=self.end,
            end=datetime(2026, 8, 5, tzinfo=timezone.utc),
            public_limit=5,
        )
        self.assertNotEqual(first["awareness_sha"], revised["awareness_sha"])


if __name__ == "__main__":
    unittest.main()
