from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.delivery import ACK_SCHEMA, DeliveryError, build_delivery, release_checkpoint
from play.digest import build_digest
from play.registry import Organization


class DeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.digest = build_digest(
            [Organization("alpha", "Alpha")],
            {"alpha": []},
            [],
            start=datetime(2026, 8, 3, tzinfo=timezone.utc),
            end=datetime(2026, 8, 4, tzinfo=timezone.utc),
            public_limit=5,
        )

    def test_prepare_is_deterministic_and_keeps_checkpoint_pending(self) -> None:
        first = build_delivery(self.digest, target_key="daily:self", channel="harness")
        second = build_delivery(self.digest, target_key="daily:self", channel="harness")
        self.assertEqual(first["delivery_id"], second["delivery_id"])
        self.assertEqual("after_matching_delivered_ack", first["checkpoint_release"]["policy"])
        self.assertEqual(self.digest["next_checkpoint"], first["checkpoint_release"]["candidate"])
        self.assertIn("# What’s new in Plays", first["message"]["body"])

    def test_matching_delivered_ack_releases_checkpoint_without_persisting_it(self) -> None:
        envelope = build_delivery(self.digest, target_key="daily:self", channel="harness")
        checkpoint = release_checkpoint(
            envelope,
            {
                "schema": ACK_SCHEMA,
                "delivery_id": envelope["delivery_id"],
                "status": "delivered",
            },
        )
        self.assertEqual(self.digest["next_checkpoint"], checkpoint)

    def test_failed_or_mismatched_ack_never_releases_checkpoint(self) -> None:
        envelope = build_delivery(self.digest, target_key="daily:self", channel="harness")
        with self.assertRaisesRegex(DeliveryError, "status delivered"):
            release_checkpoint(
                envelope,
                {
                    "schema": ACK_SCHEMA,
                    "delivery_id": envelope["delivery_id"],
                    "status": "failed",
                },
            )
        with self.assertRaisesRegex(DeliveryError, "does not match"):
            release_checkpoint(
                envelope,
                {"schema": ACK_SCHEMA, "delivery_id": "other", "status": "delivered"},
            )

    def test_tampered_envelope_never_releases_checkpoint(self) -> None:
        envelope = build_delivery(self.digest, target_key="daily:self", channel="harness")
        tampered = deepcopy(envelope)
        tampered["checkpoint_release"]["candidate"] = {
            "schema": "play.digest-checkpoint/v1",
            "last_seen_at": "2030-01-01T00:00:00+00:00",
        }
        with self.assertRaisesRegex(DeliveryError, "does not match the digest"):
            release_checkpoint(
                tampered,
                {
                    "schema": ACK_SCHEMA,
                    "delivery_id": envelope["delivery_id"],
                    "status": "delivered",
                },
            )


if __name__ == "__main__":
    unittest.main()
