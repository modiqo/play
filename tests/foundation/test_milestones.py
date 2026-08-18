from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.lib.play.milestones import claim_nudge, observe_transition, record_event
from scripts.lib.play.private_store import load_json


class PlayMilestoneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "milestones.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_each_achievement_kind_unlocks_only_once(self) -> None:
        first = record_event(
            "play_run_completed",
            run_id="run-1",
            reference="modiqo/hello",
            path=self.path,
        )
        duplicate = record_event(
            "play_run_completed",
            run_id="run-2",
            reference="modiqo/hello",
            path=self.path,
        )

        self.assertIsNotNone(first)
        self.assertIsNone(duplicate)
        self.assertEqual(1, len(load_json(self.path)["events"]))

    def test_highest_pending_achievement_coalesces_lower_nudges(self) -> None:
        for kind in (
            "play_run_completed",
            "play_created",
            "play_shared_private",
        ):
            record_event(kind, run_id="journey-1", path=self.path)

        nudge = claim_nudge(session_id="session-a", path=self.path)

        assert nudge is not None
        self.assertIn("Team playmaker unlocked", nudge)
        self.assertIsNone(claim_nudge(session_id="session-b", path=self.path))
        store = load_json(self.path)
        self.assertEqual(3, len(store["claimed_event_ids"]))
        self.assertEqual("session-a", store["last_claim"]["session_id"])

    def test_controller_transitions_emit_run_create_and_share_events(self) -> None:
        transitions = (
            ("use_receipt", "receipt_ready", "receipt", "play_run_completed"),
            ("author_release", "flow_released", "birth_capture", "play_created"),
            (
                "private_publish",
                "play_published",
                "birth_bind",
                "play_shared_private",
            ),
            (
                "public_publish",
                "play_published",
                "birth_bind",
                "play_published_public",
            ),
        )
        for source, event, target, _kind in transitions:
            with self.subTest(event=event, source=source):
                observe_transition(
                    source=source,
                    event=event,
                    target=target,
                    context={
                        "run_id": f"run-{source}",
                        "publication": {"canonical_reference": "modiqo/example"},
                    },
                    path=self.path,
                )

        kinds = {event["kind"] for event in load_json(self.path)["events"]}
        self.assertEqual({item[3] for item in transitions}, kinds)

    def test_awareness_and_failed_publication_emit_no_event(self) -> None:
        observe_transition(
            source="awareness_present",
            event="awareness_presented",
            target="awareness_offer",
            context={"run_id": "whats-new"},
            path=self.path,
        )
        observe_transition(
            source="public_publish",
            event="play_published",
            target="blocked",
            context={"run_id": "failed-publication"},
            path=self.path,
        )

        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
