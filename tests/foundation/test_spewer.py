from __future__ import annotations

import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.spewer import SpewerAdapter, SpewerAdapterError


class FakeSpewer:
    def __init__(self) -> None:
        self.submissions = 0
        self.acknowledgements = 0

    def capabilities(self) -> Mapping[str, Any]:
        return {"operations": ["submit", "observe", "result", "acknowledge"]}

    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.submissions += 1
        return {"task_id": "task-one", "event_cursor": 1, "status": "queued"}

    def observe(self, task_id: str, after: int) -> Mapping[str, Any]:
        return {
            "projection": {"task_id": task_id, "status": "completed", "event_seq": 2},
            "events": [{"seq": 2, "type": "turn.completed"}],
            "next_cursor": 2,
        }

    def result(self, task_id: str) -> Mapping[str, Any]:
        return {
            "projection": {"task_id": task_id, "status": "completed"},
            "message": {
                "message_id": "message-one",
                "task_id": task_id,
                "receipt_id": "receipt-one",
                "receipt": {
                    "receipt_id": "receipt-one",
                    "task_id": task_id,
                    "status": "completed",
                    "summary": "done",
                    "final_event_seq": 2,
                },
            },
        }

    def acknowledge(self, message_id: str, consumer_id: str) -> bool:
        self.acknowledgements += 1
        self.assertions = (message_id, consumer_id)
        return self.acknowledgements == 1


class LostFirstSubmit(FakeSpewer):
    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        handle = super().submit(request)
        if self.submissions == 1:
            raise SpewerAdapterError("injected lost submit response")
        return handle


class PlaySpewerAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="play-spewer-")
        self.database = Path(self.temporary.name) / "private" / "adapter.sqlite"
        self.transport = FakeSpewer()
        self.adapter = SpewerAdapter(self.transport, database_path=self.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_submit_poll_claim_and_ack_are_restart_safe(self) -> None:
        submitted = self.adapter.submit(
            host_run_id="play-run-one",
            continuation_ref="owner-private-continuation",
            request=request(),
        )
        repeated = self.adapter.submit(
            host_run_id="play-run-one",
            continuation_ref="owner-private-continuation",
            request=request(),
        )
        self.assertEqual(submitted["job_id"], repeated["job_id"])
        self.assertEqual(1, self.transport.submissions)

        ready = self.adapter.poll(submitted["job_id"])
        self.assertEqual("ready", ready["status"])
        claim = self.adapter.claim(submitted["job_id"], "host-claim-one")
        replay = self.adapter.claim(submitted["job_id"], "host-claim-one")
        self.assertEqual(claim, replay)
        self.assertEqual("claimed", self.adapter.poll(submitted["job_id"])["status"])
        self.assertNotIn("continuation_ref", claim)
        trusted = self.adapter.trusted_claim(submitted["job_id"], "host-claim-one")
        self.assertEqual("owner-private-continuation", trusted["continuation_ref"])
        with self.assertRaisesRegex(SpewerAdapterError, "another claim_id"):
            self.adapter.claim(submitted["job_id"], "different-claim")

        completed = self.adapter.complete(submitted["job_id"], "host-claim-one")
        repeated_completion = self.adapter.complete(
            submitted["job_id"], "host-claim-one"
        )
        self.assertEqual("acknowledged", completed["status"])
        self.assertEqual("acknowledged", repeated_completion["status"])
        self.assertEqual(("message-one", "play"), self.transport.assertions)
        self.assertEqual(2, self.transport.acknowledgements)

    def test_host_run_and_continuation_never_enter_the_spewer_request(self) -> None:
        self.adapter.submit(
            host_run_id="private-host-run",
            continuation_ref="private-continuation",
            request=request(),
        )
        changed = request()
        changed["objective"] = "different"
        with self.assertRaisesRegex(SpewerAdapterError, "another Spewer request"):
            self.adapter.submit(
                host_run_id="private-host-run",
                continuation_ref="private-continuation",
                request=changed,
            )
        with self.assertRaisesRegex(SpewerAdapterError, "another Play continuation"):
            self.adapter.submit(
                host_run_id="private-host-run",
                continuation_ref="different-continuation",
                request=request(),
            )

    def test_lost_submit_response_retries_from_durable_prepared_intent(self) -> None:
        transport = LostFirstSubmit()
        adapter = SpewerAdapter(transport, database_path=self.database)
        with self.assertRaisesRegex(SpewerAdapterError, "lost submit response"):
            adapter.submit(
                host_run_id="lost-response-run",
                continuation_ref="private-continuation",
                request=request(),
            )
        restarted = SpewerAdapter(transport, database_path=self.database)
        recovered = restarted.submit(
            host_run_id="lost-response-run",
            continuation_ref="private-continuation",
            request=request(),
        )
        self.assertEqual("submitted", recovered["status"])
        self.assertEqual(2, transport.submissions)
        leaked = request()
        leaked["private_continuation"] = {"continuation_id": "secret"}
        with self.assertRaisesRegex(SpewerAdapterError, "must not enter"):
            self.adapter.submit(
                host_run_id="another-run",
                continuation_ref="private-continuation",
                request=leaked,
            )

    def test_adapter_database_and_parent_directory_are_owner_private(self) -> None:
        self.assertEqual(0o600, stat.S_IMODE(self.database.stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE(self.database.parent.stat().st_mode))

    def test_each_command_teaches_its_state_transition_and_next_action(self) -> None:
        executable = ROOT / "scripts" / "bin" / "play-spewer"
        for command in ("submit", "poll", "watch", "claim", "complete", "status", "pending"):
            with self.subTest(command=command):
                completed = subprocess.run(
                    [str(executable), command, "--help"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertIn("State:", completed.stdout)
                self.assertIn("Next", completed.stdout)


def request() -> dict[str, Any]:
    return {
        "protocol_version": "0.1",
        "idempotency_key": "play-run-one:step-one",
        "objective": "perform one bounded task",
        "callback": {"mode": "poll", "consumer_id": "play"},
    }


if __name__ == "__main__":
    unittest.main()
