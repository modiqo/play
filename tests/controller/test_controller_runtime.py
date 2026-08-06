from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.controller import (
    ControllerEvent,
    ControllerRuntime,
    ControllerRuntimeError,
    EventId,
    GuardId,
)


class ControllerRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = ControllerRuntime(ROOT)

    def cursor(self):
        return self.runtime.initial_cursor(run_id="run-1", task_key="task-1")

    def test_compiles_the_authoritative_bundle(self) -> None:
        self.assertEqual("qualify", self.runtime.bundle.initial)
        self.assertEqual(53, len(self.runtime.bundle.states))
        self.assertEqual(
            {"blocked", "completed", "exited", "receipt"},
            self.runtime.bundle.terminals,
        )
        self.assertGreater(self.runtime.compile_ns, 0)

    def test_executes_an_unconditional_transition(self) -> None:
        result = self.runtime.step(
            self.cursor(),
            ControllerEvent(
                id=EventId("conversation"),
                payload={"reason": "ordinary repository work"},
                guards={},
            ),
        )
        self.assertEqual("exited", result.cursor.state)
        self.assertEqual(1, result.cursor.transition_seq)
        self.assertEqual("record_non_outcome_exit", result.transition.mutation)
        self.assertIsNone(result.transition.guard)
        self.assertGreater(result.timing.step_ns, 0)

    def test_ordered_guard_selects_the_first_satisfied_branch(self) -> None:
        cursor = self.cursor()
        cursor = self.runtime.step(
            cursor,
            ControllerEvent(
                id=EventId("outcome_request"),
                payload={
                    "request": {"intent": "do work", "requested_outcome": "result"},
                    "modality_policy": {},
                },
                guards={},
            ),
        ).cursor
        result = self.runtime.step(
            cursor,
            ControllerEvent(
                id=EventId("search_ready"),
                payload={
                    "search": {
                        "complete": True,
                        "query": "do work",
                        "sources": [],
                        "result_refs": [],
                        "results": [],
                        "play_choices": [],
                    }
                },
                guards={
                    GuardId("search_only_requested"): False,
                    GuardId("search_is_complete"): True,
                },
            ),
        )
        self.assertEqual("classify", result.cursor.state)
        self.assertEqual("search_is_complete", result.transition.guard)

    def test_guard_fallback_is_fail_closed_and_deterministic(self) -> None:
        cursor = self.cursor()
        cursor = self.runtime.step(
            cursor,
            ControllerEvent(
                id=EventId("outcome_request"),
                payload={
                    "request": {"intent": "do work", "requested_outcome": "result"},
                    "modality_policy": {},
                },
                guards={},
            ),
        ).cursor
        result = self.runtime.step(
            cursor,
            ControllerEvent(
                id=EventId("search_ready"),
                payload={
                    "search": {
                        "complete": False,
                        "query": "do work",
                        "sources": [],
                        "result_refs": [],
                        "results": [],
                        "play_choices": [],
                    }
                },
                guards={},
            ),
        )
        self.assertEqual("blocked", result.cursor.state)
        self.assertEqual("record_incomplete_search", result.transition.mutation)

    def test_rejects_unknown_event(self) -> None:
        with self.assertRaisesRegex(ControllerRuntimeError, "does not accept event"):
            self.runtime.step(
                self.cursor(),
                ControllerEvent(EventId("invented"), payload={}, guards={}),
            )

    def test_rejects_incomplete_event_payload(self) -> None:
        with self.assertRaisesRegex(ControllerRuntimeError, "missing required fields: reason"):
            self.runtime.step(
                self.cursor(),
                ControllerEvent(EventId("conversation"), payload={}, guards={}),
            )

    def test_rejects_cursor_from_another_bundle(self) -> None:
        cursor = self.cursor()
        foreign = cursor.__class__(
            **{**cursor.__dict__, "bundle_sha256": "0" * 64}
        )
        with self.assertRaisesRegex(ControllerRuntimeError, "different controller bundle"):
            self.runtime.step(
                foreign,
                ControllerEvent(
                    EventId("conversation"),
                    payload={"reason": "test"},
                    guards={},
                ),
            )

    def test_terminal_state_rejects_events(self) -> None:
        terminal = self.runtime.step(
            self.cursor(),
            ControllerEvent(
                EventId("conversation"),
                payload={"reason": "test"},
                guards={},
            ),
        ).cursor
        with self.assertRaisesRegex(ControllerRuntimeError, "terminal state"):
            self.runtime.step(
                terminal,
                ControllerEvent(EventId("anything"), payload={}, guards={}),
            )


if __name__ == "__main__":
    unittest.main()
