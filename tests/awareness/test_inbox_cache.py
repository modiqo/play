from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.inbox_cache import (
    cached_line,
    read_cache,
    refresh_cache,
    summary_line,
)
from play.registry import Organization


def _digest(new: int, revised: int) -> dict:
    def item(index: int, kind: str) -> dict:
        return {
            "reference": f"acme/play-{kind}-{index}",
            "owner": "acme",
            "name": f"play-{kind}-{index}",
            "kind": kind,
            "visibility": "private",
            "timestamp": "2026-08-10T00:00:00+00:00",
            "description": "A test play.",
            "actionable": True,
        }

    return {
        "schema": "play.digest/v1",
        "complete": True,
        "window": {
            "start": "2026-08-04T00:00:00+00:00",
            "end": "2026-08-11T00:00:00+00:00",
            "timezone": "UTC",
        },
        "sources": [],
        "organizations": [{"slug": "acme", "display_name": "Acme"}],
        "org_updates": {
            "new": [item(i, "new") for i in range(new)],
            "revised": [item(i, "revised") for i in range(revised)],
            "revised_complete": True,
        },
        "ranking": {
            "label": "Popular public Plays",
            "complete": True,
            "eligible_count": 1,
            "organization_count": 1,
        },
        "public_top": [],
        "public_groups": [],
        "public_sample": [
            {
                "reference": "acme/hello",
                "name": "hello",
                "owner": "acme",
                "owner_kind": "org",
                "description": "Say hello.",
                "download_count": 1,
                "parameters": {},
            }
        ],
        "sample": {
            "strategy": "random",
            "limit": 10,
            "available_count": 1,
            "sampled_count": 1,
        },
        "personal_stats": {"reason": "run analytics are not collected"},
    }


class SummaryLineTest(unittest.TestCase):
    def test_quiet_when_nothing_new(self) -> None:
        self.assertIsNone(summary_line(_digest(0, 0)))

    def test_counts_and_owner_in_one_line(self) -> None:
        line = summary_line(_digest(2, 1))
        assert line is not None
        self.assertIn("2 new Plays", line)
        self.assertIn("1 revised Play", line)
        self.assertIn("acme", line)
        self.assertIn("what's new", line)
        self.assertNotIn("\n", line)

    def test_malformed_digest_is_quiet_not_fatal(self) -> None:
        self.assertIsNone(summary_line({}))


class InboxCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        base = Path(self._temporary.name)
        self.cache_path = base / "inbox-cache.json"
        self.state_path = base / "digest-state.json"

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _refresh(self, digest: dict, **kwargs):
        return refresh_cache(
            cache_path=self.cache_path,
            state_path=self.state_path,
            collect=lambda **_: digest,
            load_flows=lambda slugs: {
                "acme": [
                    {
                        "id": "play-123",
                        "owner_id": "org-456",
                        "name": "ship-and-tell",
                        "description": "Deploy, smoke, and post a summary.",
                        "visibility": "private",
                    }
                ]
            },
            organizations=[Organization("acme", "acme")],
            **kwargs,
        )

    def test_refresh_stores_both_tiers_and_line_reads_without_network(self) -> None:
        cache = self._refresh(_digest(2, 0))
        self.assertTrue(cache["refreshed"])
        stored = read_cache(cache_path=self.cache_path)
        assert stored is not None
        self.assertEqual(2, stored["counts"]["new"])
        self.assertEqual(stored["summary_line"], cached_line(cache_path=self.cache_path))
        self.assertIn("**hello** — Say hello.", stored["markdown"])
        self.assertEqual(
            "acme/play-new-0",
            stored["digest"]["org_updates"]["new"][0]["reference"],
        )
        self.assertEqual(
            [
                {
                    "reference": "acme/ship-and-tell",
                    "name": "ship-and-tell",
                    "description": "Deploy, smoke, and post a summary.",
                    "visibility": "private",
                    "skill_id": "play-123",
                    "owner_id": "org-456",
                }
            ],
            stored["catalog"],
        )

    def test_quiet_inbox_stores_no_line(self) -> None:
        self._refresh(_digest(0, 0))
        self.assertIsNone(cached_line(cache_path=self.cache_path))

    def test_if_older_than_skips_a_fresh_cache(self) -> None:
        self._refresh(_digest(1, 0))
        skipped = self._refresh(_digest(5, 5), if_older_than_hours=6)
        self.assertFalse(skipped["refreshed"])
        stored = read_cache(cache_path=self.cache_path)
        assert stored is not None
        self.assertEqual(1, stored["counts"]["new"])

    def test_if_older_than_refreshes_a_fresh_legacy_digest_without_sample(self) -> None:
        self._refresh(_digest(1, 0))
        stored = read_cache(cache_path=self.cache_path)
        assert stored is not None
        stored["digest"].pop("public_sample")
        from play.private_store import atomic_write_json

        atomic_write_json(self.cache_path, stored)
        refreshed = self._refresh(_digest(3, 0), if_older_than_hours=6)

        self.assertTrue(refreshed["refreshed"])
        latest = read_cache(cache_path=self.cache_path)
        assert latest is not None
        self.assertEqual(3, latest["counts"]["new"])
        self.assertEqual(1, latest["digest"]["ranking"]["organization_count"])
        self.assertEqual("acme/hello", latest["digest"]["public_sample"][0]["reference"])

    def test_if_older_than_refreshes_a_stale_cache(self) -> None:
        self._refresh(_digest(1, 0))
        stored = read_cache(cache_path=self.cache_path)
        assert stored is not None
        stale = datetime.now(timezone.utc) - timedelta(hours=7)
        stored["fetched_at"] = stale.isoformat(timespec="seconds")
        from play.private_store import atomic_write_json

        atomic_write_json(self.cache_path, stored)
        refreshed = self._refresh(_digest(3, 0), if_older_than_hours=6)
        self.assertTrue(refreshed["refreshed"])
        latest = read_cache(cache_path=self.cache_path)
        assert latest is not None
        self.assertEqual(3, latest["counts"]["new"])

    def test_missing_cache_reads_as_absent(self) -> None:
        self.assertIsNone(read_cache(cache_path=self.cache_path))
        self.assertIsNone(cached_line(cache_path=self.cache_path))

    def test_public_catalog_is_canonical_and_fingerprinted(self) -> None:
        flows = [
            {
                "name": "z-last",
                "description": "Last by canonical reference.",
                "visibility": "public",
                "version": "1.2.0",
                "status": "released",
                "tags": ["release", "github", "release"],
                "labels": ["Engineering", "Automation"],
            },
            {
                "name": "a-first",
                "description": "First by canonical reference.",
                "visibility": "public",
                "version": "0.3.0",
                "status": "approved",
            },
        ]

        first = refresh_cache(
            cache_path=self.cache_path,
            state_path=self.state_path,
            collect=lambda **_: _digest(0, 0),
            load_flows=lambda _: {"acme": list(flows)},
            organizations=[Organization("acme", "Acme")],
            require_complete_catalog=True,
        )
        second_path = self.cache_path.with_name("second-cache.json")
        second = refresh_cache(
            cache_path=second_path,
            state_path=self.state_path,
            collect=lambda **_: _digest(0, 0),
            load_flows=lambda _: {"acme": list(reversed(flows))},
            organizations=[Organization("acme", "Acme")],
            require_complete_catalog=True,
        )

        self.assertTrue(first["catalog_complete"])
        self.assertEqual(2, first["counts"]["public"])
        self.assertEqual(first["catalog_sha256"], second["catalog_sha256"])
        self.assertEqual(
            ["acme/a-first", "acme/z-last"],
            [item["reference"] for item in first["public_catalog"]],
        )
        self.assertEqual(
            ["Automation", "Engineering"], first["public_catalog"][1]["labels"]
        )
        self.assertEqual(
            ["github", "release"], first["public_catalog"][1]["tags"]
        )

    def test_required_complete_catalog_failure_preserves_last_snapshot(self) -> None:
        self._refresh(_digest(1, 0))
        before = self.cache_path.read_bytes()

        with self.assertRaisesRegex(RuntimeError, "registry unavailable"):
            refresh_cache(
                cache_path=self.cache_path,
                state_path=self.state_path,
                collect=lambda **_: _digest(2, 0),
                load_flows=lambda _: (_ for _ in ()).throw(
                    RuntimeError("registry unavailable")
                ),
                organizations=[Organization("acme", "Acme")],
                require_complete_catalog=True,
            )

        self.assertEqual(before, self.cache_path.read_bytes())

    def test_maintenance_failure_returns_last_verified_snapshot(self) -> None:
        previous = self._refresh(_digest(1, 0))
        before = self.cache_path.read_bytes()

        retained = refresh_cache(
            cache_path=self.cache_path,
            state_path=self.state_path,
            collect=lambda **_: _digest(2, 0),
            load_flows=lambda _: (_ for _ in ()).throw(
                RuntimeError("registry unavailable")
            ),
            organizations=[Organization("acme", "Acme")],
        )

        self.assertFalse(retained["refreshed"])
        self.assertEqual(previous["catalog_sha256"], retained["catalog_sha256"])
        self.assertEqual(before, self.cache_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
