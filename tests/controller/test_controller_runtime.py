from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.controller import (
    ControllerEvent,
    ControllerRuntime,
    ControllerRuntimeError,
    EventId,
    GuardId,
    StateId,
)


class ControllerRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = ControllerRuntime(ROOT)

    def cursor(self):
        cursor = self.runtime.initial_cursor(run_id="run-1", task_key="task-1")
        return self.runtime.step(
            cursor,
            ControllerEvent(
                id=EventId("ordinary_play_invocation"),
                payload={"onboarding": {"classify_ns": 1}},
                guards={},
            ),
        ).cursor

    def initial_cursor(self):
        return self.runtime.initial_cursor(run_id="run-1", task_key="task-1")

    def test_compiles_the_authoritative_bundle(self) -> None:
        self.assertEqual("invoke", self.runtime.bundle.initial)
        self.assertEqual(67, len(self.runtime.bundle.states))
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
        self.assertEqual(2, result.cursor.transition_seq)
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

    def test_empty_invocation_enters_typed_onboarding_probe(self) -> None:
        result = self.runtime.step(
            self.initial_cursor(),
            ControllerEvent(
                id=EventId("empty_play_invocation"),
                payload={"onboarding": {"intent": "greeting", "classify_ns": 10}},
                guards={},
            ),
        )
        self.assertEqual("onboarding_probe", result.cursor.state)
        self.assertEqual("start_greeting_onboarding", result.transition.mutation)

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

    def test_complete_run_output_is_required_before_verification(self) -> None:
        run_cursor = replace(self.cursor(), state=StateId("use_run"))
        output_cursor = self.runtime.step(
            run_cursor,
            ControllerEvent(
                id=EventId("play_run_ready"),
                payload={
                    "play": {"version": "1.2.0"},
                    "resolution": {"local_state": "exact_ready", "pull_performed": False},
                    "result_ref": "result:1",
                    "response_refs": ["response:1"],
                    "artifact_refs": [],
                    "effects": ["read"],
                    "output": {
                        "mode": "detailed",
                        "detail": "full",
                        "source": "rote_human_presentation",
                        "format": "markdown",
                        "primary": "# Result",
                        "manifest": {
                            "response_refs": ["response:1"],
                            "artifact_refs": [],
                            "effects": ["read"],
                        },
                        "truncated": False,
                        "full_output_ref": None,
                    },
                },
                guards={},
            ),
        ).cursor
        self.assertEqual("use_output", output_cursor.state)

        verify_cursor = self.runtime.step(
            output_cursor,
            ControllerEvent(
                id=EventId("detailed_output_ready"),
                payload={
                    "output": {
                        "presentation_markdown": "# Play result\n\n# Result",
                        "presentation_sha256": "a" * 64,
                        "inline_bytes": 23,
                        "primary_bytes": 8,
                        "format_ns": 100,
                        "truncated": False,
                        "full_output_ref": None,
                    }
                },
                guards={},
            ),
        ).cursor
        self.assertEqual("use_verify", verify_cursor.state)

    def test_call_route_requires_catalog_discovery_before_handoff(self) -> None:
        route_cursor = replace(self.cursor(), state=StateId("explore_route"))
        dispatch_cursor = self.runtime.step(
            route_cursor,
            ControllerEvent(
                id=EventId("route_selected"),
                payload={
                    "execution": {"owner": "rote-using-adapters"},
                    "route": {"modalities": ["call"]},
                    "justification": "A typed API is the smallest verifiable route.",
                    "adapter_discovery": {"query": "stripe"},
                },
                guards={GuardId("route_within_policy"): True},
            ),
        ).cursor
        self.assertEqual("explore_dispatch", dispatch_cursor.state)

        discovery_cursor = self.runtime.step(
            dispatch_cursor,
            ControllerEvent(
                id=EventId("adapter_discovery_required"),
                payload={
                    "execution": {"owner": "rote-using-adapters"},
                    "route": {"modalities": ["call"]},
                },
                guards={},
            ),
        ).cursor
        self.assertEqual("adapter_discover", discovery_cursor.state)

        choice = {
            "id": "stripe",
            "label": "Stripe REST API",
            "description": "Catalog OpenAPI adapter for Stripe.",
            "source": "catalog",
            "provider": "Stripe",
            "category": "Payments",
            "substrate": "openapi",
            "auth_shape": "static_token",
            "health": "unknown",
            "install_impact": "local-write",
            "next_command": "rote adapter catalog info stripe --json",
        }
        offer_cursor = self.runtime.step(
            discovery_cursor,
            ControllerEvent(
                id=EventId("adapter_choices_ready"),
                payload={
                    "adapter_discovery": {
                        "status": "catalog_choices",
                        "searched_sources": ["installed", "catalog"],
                        "choices": [choice],
                        "evidence_refs": ["catalog-search:stripe"],
                    }
                },
                guards={},
            ),
        ).cursor
        self.assertEqual("adapter_offer", offer_cursor.state)

        handoff_cursor = self.runtime.step(
            offer_cursor,
            ControllerEvent(
                id=EventId("adapter_source_selected"),
                payload={
                    "prompt_version": "1",
                    "selected_at": "2026-08-06T00:00:00Z",
                    "adapter_discovery": {"selected_id": "stripe"},
                },
                guards={},
            ),
        ).cursor
        self.assertEqual("explore_handoff", handoff_cursor.state)

    def test_release_cannot_cross_publication_boundary_before_birth_capture(self) -> None:
        release_cursor = replace(self.cursor(), state=StateId("author_release"))
        payload = {
            "candidate": {
                "released_flow": "posthog-dau-new@0.0.1",
                "publication_status": "published",
            },
            "play": {"version": "0.0.1"},
            "verification_refs": ["release:posthog-dau-new@0.0.1"],
        }
        result = self.runtime.step(
            release_cursor,
            ControllerEvent(
                id=EventId("flow_released"),
                payload=payload,
                guards={GuardId("released_candidate_is_unpublished"): True},
            ),
        )
        self.assertEqual("blocked", result.cursor.state)
        self.assertEqual("record_publication_boundary_violation", result.transition.mutation)

    def test_unpublished_release_enters_birth_capture_despite_spoofed_false_guard(self) -> None:
        release_cursor = replace(self.cursor(), state=StateId("author_release"))
        result = self.runtime.step(
            release_cursor,
            ControllerEvent(
                id=EventId("flow_released"),
                payload={
                    "candidate": {
                        "released_flow": "posthog-dau-new@0.0.2",
                        "publication_status": "unpublished",
                    },
                    "play": {"version": "0.0.2"},
                    "verification_refs": ["release:posthog-dau-new@0.0.2"],
                },
                guards={GuardId("released_candidate_is_unpublished"): False},
            ),
        )
        self.assertEqual("birth_capture", result.cursor.state)

    def test_publication_receipt_must_match_captured_birth(self) -> None:
        publish_cursor = replace(self.cursor(), state=StateId("public_publish"))
        captured = "a" * 64
        base_payload = {
            "publication": {
                "canonical_reference": "chetanconikee/posthog-dau-new@0.0.2",
                "uri": "https://play.modiqo.ai/chetanconikee/posthog-dau-new@0.0.2",
                "install_uri": "https://play.modiqo.ai/install?play=chetanconikee/posthog-dau-new@0.0.2",
                "birth_sha256": "b" * 64,
            },
            "visibility": "public",
            "owner": "chetanconikee",
            "play": {"version": "0.0.2"},
            "birth": {"sha256": captured},
        }
        mismatch = self.runtime.step(
            publish_cursor,
            ControllerEvent(
                id=EventId("play_published"),
                payload=base_payload,
                guards={GuardId("public_publication_matches_captured_birth"): True},
            ),
        )
        self.assertEqual("blocked", mismatch.cursor.state)

        matching_payload = {
            **base_payload,
            "publication": {**base_payload["publication"], "birth_sha256": captured},
        }
        matched = self.runtime.step(
            publish_cursor,
            ControllerEvent(
                id=EventId("play_published"),
                payload=matching_payload,
                guards={GuardId("public_publication_matches_captured_birth"): False},
            ),
        )
        self.assertEqual("birth_bind", matched.cursor.state)

    def test_direct_registry_publication_is_a_typed_blocking_event(self) -> None:
        release_cursor = replace(self.cursor(), state=StateId("author_release"))
        result = self.runtime.step(
            release_cursor,
            ControllerEvent(
                id=EventId("publication_boundary_violated"),
                payload={
                    "candidate": {"publication_status": "published"},
                    "publication": {
                        "canonical_reference": "chetanconikee/posthog-dau-new@0.0.1"
                    },
                    "reason": "registry flow published before birth_capture",
                    "evidence_refs": ["registry:posthog-dau-new@0.0.1"],
                },
                guards={},
            ),
        )
        self.assertEqual("blocked", result.cursor.state)
        self.assertNotEqual("completed", result.cursor.state)

    def test_release_receipt_requires_explicit_publication_status(self) -> None:
        release_cursor = replace(self.cursor(), state=StateId("author_release"))
        with self.assertRaisesRegex(
            ControllerRuntimeError, "candidate.publication_status"
        ):
            self.runtime.step(
                release_cursor,
                ControllerEvent(
                    id=EventId("flow_released"),
                    payload={
                        "candidate": {"released_flow": "posthog-dau-new@0.0.1"},
                        "play": {"version": "0.0.1"},
                        "verification_refs": ["release:posthog-dau-new@0.0.1"],
                    },
                    guards={GuardId("released_candidate_is_unpublished"): True},
                ),
            )

    def test_rejects_unknown_event(self) -> None:
        with self.assertRaisesRegex(ControllerRuntimeError, "does not accept event"):
            self.runtime.step(
                self.initial_cursor(),
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
