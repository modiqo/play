from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.digest import build_digest, classify_updates, rank_public
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
        self.assertFalse(digest["ranking"]["complete"])


if __name__ == "__main__":
    unittest.main()
