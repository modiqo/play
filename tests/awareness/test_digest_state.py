from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.digest_state import (
    DigestStateError,
    compare_digest,
    load_entry,
    save_entry,
    scope_contract,
    scope_key,
)
from play.registry import Organization


class DigestStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scope = scope_contract(
            [Organization("alpha", "Alpha")],
            window_days=1,
            public_limit=5,
            inspection_budget=8,
            update_metadata_budget=100,
            update_inspection_budget=4,
        )
        self.key = scope_key(self.scope)
        self.digest = {
            "awareness_sha": "a" * 64,
            "next_checkpoint": {
                "schema": "play.digest-checkpoint/v1",
                "last_seen_at": "2026-08-04T12:00:00+00:00",
            },
        }

    def test_scope_key_is_order_independent(self) -> None:
        reversed_scope = scope_contract(
            [Organization("beta", "Beta"), Organization("alpha", "Alpha")],
            window_days=1,
            public_limit=5,
            inspection_budget=8,
            update_metadata_budget=100,
            update_inspection_budget=4,
        )
        ordered_scope = scope_contract(
            [Organization("alpha", "Alpha"), Organization("beta", "Beta")],
            window_days=1,
            public_limit=5,
            inspection_budget=8,
            update_metadata_budget=100,
            update_inspection_budget=4,
        )
        self.assertEqual(scope_key(ordered_scope), scope_key(reversed_scope))

    def test_save_and_load_store_only_scope_sha_and_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "digest-state.json"
            save_entry(path, key=self.key, scope=self.scope, digest=self.digest)
            entry = load_entry(path, self.key)
            self.assertEqual("a" * 64, entry["awareness_sha"])
            self.assertEqual(self.digest["next_checkpoint"], entry["checkpoint"])
            self.assertNotIn("digest", entry)
            self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_compare_distinguishes_initial_unchanged_and_changed(self) -> None:
        self.assertEqual("initial", compare_digest(self.digest, None))
        previous = {
            "scope": self.scope,
            "awareness_sha": "a" * 64,
            "checkpoint": self.digest["next_checkpoint"],
        }
        self.assertEqual("unchanged", compare_digest(self.digest, previous))
        changed = {**self.digest, "awareness_sha": "b" * 64}
        self.assertEqual("changed", compare_digest(changed, previous))

    def test_malformed_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "digest-state.json"
            path.write_text("{}")
            with self.assertRaisesRegex(DigestStateError, "play.digest-state/v1"):
                load_entry(path, self.key)


if __name__ == "__main__":
    unittest.main()
