from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.digest import (
    build_digest,
    classify_updates,
    rank_public,
    render_markdown,
    supports_domain_discovery,
)
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
        self.assertIn("Revisions are unavailable", render_markdown(digest))
        self.assertIn("No new publications were found", render_markdown(digest))
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

    def test_whats_new_defers_individual_cards_until_a_domain_is_selected(self) -> None:
        grouped = {
            "alpha": [
                {
                    "name": "weekly-report",
                    "description": "Original description",
                    "visibility": "public",
                    "created_at": "2026-08-03T04:00:00+00:00",
                    "latest_version_created_at": "2026-08-03T04:00:00+00:00",
                }
            ]
        }
        digest = build_digest(
            [Organization("alpha", "Alpha Team")],
            grouped,
            [],
            start=self.start,
            end=self.end,
            public_limit=10,
            update_metadata={
                "alpha/weekly-report": {
                    "description": "A concise weekly customer report.",
                    "creator_name": "Alice Example",
                    "creator_status": "available",
                    "version": "1.0.0",
                }
            },
        )
        rendered = render_markdown(digest)
        self.assertIn("# What’s new in Plays", rendered)
        self.assertIn("1 new or revised Play", rendered)
        self.assertNotIn("weekly-report", rendered)
        self.assertNotIn("| Play |", rendered)
        self.assertEqual("unavailable", digest["capabilities"]["run_metrics"]["status"])

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

    def test_public_stats_are_grouped_by_owner_and_show_both_counters(self) -> None:
        digest = build_digest(
            [Organization("modiqo", "Modiqo")],
            {"modiqo": []},
            [
                (
                    "modiqo",
                    {
                        "name": "hello",
                        "visibility": "public",
                        "exact_reference": "modiqo/hello@0.1.0",
                        "owner_kind": "org",
                        "download_count": 7,
                        "install_count": 2,
                    },
                )
            ],
            start=self.start,
            end=self.end,
            public_limit=10,
            ranking_fetch_elapsed_ms=15.25,
            ranking_fetch_workers=4,
        )
        self.assertEqual("modiqo", digest["public_groups"][0]["owner"])
        self.assertEqual("org", digest["public_groups"][0]["owner_kind"])
        self.assertEqual(1, digest["ranking"]["eligible_count"])
        self.assertEqual(1, digest["ranking"]["organization_count"])
        self.assertEqual(1, digest["public_domains"][0]["count"])
        self.assertEqual("modiqo/hello", digest["public_top"][0]["base_reference"])
        self.assertEqual("parallel", digest["ranking"]["fetch"]["mode"])
        self.assertEqual(15.25, digest["ranking"]["fetch"]["elapsed_ms"])
        rendered = render_markdown(digest)
        self.assertIn("1 runnable public Play", rendered)
        self.assertIn("**Modiqo** — 1 Play", rendered)
        self.assertIn("Counts cover runnable public cards", rendered)

    def test_first_digest_congratulates_before_the_summary(self) -> None:
        digest = build_digest(
            [Organization("modiqo", "Modiqo")],
            {"modiqo": []},
            [],
            start=self.start,
            end=self.end,
            public_limit=10,
        )
        digest["memory"] = {"status": "initial"}
        rendered = render_markdown(digest)
        self.assertTrue(rendered.startswith("**Nice—you’ve taken the first step."))
        self.assertLess(rendered.index("taken the first step"), rendered.index("What’s new"))

    def test_partial_catalog_uses_at_least_language(self) -> None:
        digest = build_digest(
            [Organization("modiqo", "Modiqo")],
            {"modiqo": []},
            [
                (
                    "modiqo",
                    {
                        "name": "hello",
                        "visibility": "public",
                        "download_count": 1,
                    },
                )
            ],
            start=self.start,
            end=self.end,
            public_limit=10,
            ranking_complete=False,
            ranking_omitted_count=1,
        )
        self.assertIn("at least **1 runnable public Play**", render_markdown(digest))

    def test_legacy_cached_digest_without_domains_is_not_discovery_compatible(self) -> None:
        digest = build_digest(
            [Organization("modiqo", "Modiqo")],
            {"modiqo": []},
            [
                (
                    "modiqo",
                    {
                        "name": "hello",
                        "visibility": "public",
                        "download_count": 1,
                    },
                )
            ],
            start=self.start,
            end=self.end,
            public_limit=10,
        )
        self.assertTrue(supports_domain_discovery(digest))
        digest.pop("public_domains")
        self.assertFalse(supports_domain_discovery(digest))

    def test_domain_choices_keep_total_count_but_offer_most_recent_plays(self) -> None:
        grouped = {
            "engineering": [
                {
                    "name": "older",
                    "visibility": "public",
                    "created_at": "2026-07-01T00:00:00+00:00",
                    "latest_version_created_at": "2026-07-02T00:00:00+00:00",
                },
                {
                    "name": "newer",
                    "visibility": "public",
                    "created_at": "2026-07-03T00:00:00+00:00",
                    "latest_version_created_at": "2026-08-03T00:00:00+00:00",
                },
            ]
        }
        public = [
            (
                "engineering",
                {
                    "name": name,
                    "visibility": "public",
                    "download_count": downloads,
                },
            )
            for name, downloads in (("older", 100), ("newer", 1))
        ]
        digest = build_digest(
            [Organization("engineering", "Engineering")],
            grouped,
            public,
            start=self.start,
            end=self.end,
            public_limit=10,
        )

        domain = digest["public_domains"][0]
        self.assertEqual(2, domain["count"])
        self.assertEqual(5, domain["recent_play_limit"])
        self.assertEqual(["newer", "older"], [play["name"] for play in domain["plays"]])

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
