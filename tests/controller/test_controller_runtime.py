from __future__ import annotations

import json
import sys
import unittest
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.controller import (
    ControllerEvent,
    ControllerRuntime,
    ControllerRuntimeError,
    EventId,
    GuardId,
    StateId,
    decode_session,
    encode_session,
)
from play.runtime_actions import advance_until_yield
from play.runtime_context import RuntimeContextError, validate_mutation_contract


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
        self.assertEqual(80, len(self.runtime.bundle.states))
        self.assertEqual(
            {"blocked", "completed", "exited", "receipt"},
            self.runtime.bundle.terminals,
        )
        self.assertGreater(self.runtime.compile_ns, 0)

    def test_runtime_context_fails_closed_when_mutation_contract_changes(self) -> None:
        with self.assertRaisesRegex(RuntimeContextError, "mutations changed"):
            validate_mutation_contract(["invented_mutation"])

    def test_projects_only_the_current_state_contract(self) -> None:
        projection = self.runtime.project(self.initial_cursor()).as_dict()

        self.assertEqual("play.runtime-projection/v1", projection["schema"])
        self.assertEqual("invoke", projection["state"]["id"])
        self.assertEqual("deterministic_action", projection["state"]["boundary"])
        self.assertEqual("classify_play_invocation", projection["instruction"]["id"])
        self.assertIn("ordinary_play_invocation", projection["accepted_events"])
        self.assertNotIn("qualify_request", str(projection))

    def test_advance_returns_the_next_compact_instruction(self) -> None:
        result = self.runtime.advance(
            self.initial_cursor(),
            ControllerEvent(
                id=EventId("ordinary_play_invocation"),
                payload={"onboarding": {"classify_ns": 1}},
                guards={},
            ),
        ).as_dict()

        self.assertEqual("play.runtime-advance/v1", result["schema"])
        self.assertEqual("qualify", result["projection"]["state"]["id"])
        self.assertEqual("evaluator_action", result["projection"]["state"]["boundary"])
        self.assertEqual("qualify_request", result["projection"]["instruction"]["id"])
        self.assertIn(
            "outcome_request",
            result["projection"]["instruction"]["preflight_required_for_events"],
        )
        self.assertNotIn(
            "conversation",
            result["projection"]["instruction"]["preflight_required_for_events"],
        )

    def test_terminal_projection_has_no_instruction(self) -> None:
        terminal = self.runtime.step(
            self.cursor(),
            ControllerEvent(
                id=EventId("conversation"),
                payload={"reason": "ordinary repository work"},
                guards={},
            ),
        ).cursor

        projection = self.runtime.project(terminal).as_dict()
        self.assertEqual("terminal", projection["state"]["boundary"])
        self.assertIsNone(projection["instruction"])
        self.assertEqual({}, projection["accepted_events"])

    def test_delegated_projection_names_the_exact_rote_specialist(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-specialist",
            task_key="task-specialist",
            request_original="Fetch recent emails",
        )
        for state, expected in (
            ("adapter_discover", "rote-adapter-create"),
            ("adapter_converge", "rote-adapter-create"),
            ("use_auth_repair_execute", "rote-adapter-config"),
        ):
            projection = self.runtime.project(
                replace(session.cursor, state=StateId(state)), session.context
            ).as_dict()
            self.assertEqual(expected, projection["instruction"]["specialist"])

        context = dict(session.context)
        context["execution"] = dict(context["execution"])
        context["execution"]["owner"] = "rote-using-adapters"
        projection = self.runtime.project(
            replace(session.cursor, state=StateId("explore_execute")), context
        ).as_dict()
        self.assertEqual(
            "rote-using-adapters", projection["instruction"]["specialist"]
        )

    def test_session_initializes_complete_valid_context(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1",
            task_key="task-1",
            request_original="Find a Play for release notes",
        )

        self.assertEqual("play.context/v1", session.context["schema"])
        self.assertEqual("invoke", session.context["state"])
        self.assertEqual("detailed", session.context["output_policy"]["mode"])
        self.assertEqual("unknown", session.context["candidate"]["publication_status"])
        projection = self.runtime.project_session(session).as_dict()
        self.assertEqual(
            {"request": {"original": "Find a Play for release notes"}},
            projection["instruction"]["input"],
        )

    def test_session_advance_applies_event_and_checkpoints_context(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Repository work"
        )
        advanced = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("ordinary_play_invocation"),
                payload={"onboarding": {"classify_ns": 42}},
                guards={},
            ),
        )

        self.assertEqual("qualify", advanced.session.context["state"])
        self.assertEqual(1, advanced.session.context["transition_seq"])
        self.assertEqual(42, advanced.session.context["onboarding"]["classify_ns"])
        self.assertEqual("ordinary_play_invocation", advanced.session.context["last_event"]["id"])
        self.assertIsNotNone(advanced.projection.instruction)
        assert advanced.projection.instruction is not None
        self.assertEqual(
            {"request": {"original": "Repository work"}},
            advanced.projection.instruction["input"],
        )

    def test_session_token_round_trips_without_exposing_full_context(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Repository work"
        )
        token = encode_session(session)

        self.assertLess(len(token), 5000)
        self.assertNotIn("Repository work", token)
        restored = decode_session(token)
        self.assertEqual(session, restored)

    def test_session_token_rejects_corruption(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Repository work"
        )
        token = encode_session(session)
        corrupted = token[:-1] + ("0" if token[-1] != "0" else "1")

        with self.assertRaisesRegex(ControllerRuntimeError, "invalid runtime session token"):
            decode_session(corrupted)

    def test_session_requires_ready_preflight_only_for_play_trajectory(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Find release notes"
        )
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("ordinary_play_invocation"),
                payload={"onboarding": {"classify_ns": 1}},
                guards={},
            ),
        ).session
        event = ControllerEvent(
            id=EventId("outcome_request"),
            payload={
                "request": {"intent": "release notes", "requested_outcome": "notes"},
                "modality_policy": session.context["modality_policy"],
            },
            guards={},
        )

        with self.assertRaisesRegex(ControllerRuntimeError, "ready Play preflight"):
            self.runtime.advance_session(session, event)

        ready = self.runtime.confirm_preflight(
            session, {"schema": "play.preflight/v1", "ready": True}
        )
        advanced = self.runtime.advance_session(ready, event)
        self.assertEqual("search", advanced.session.cursor.state)

    def test_session_exit_does_not_require_preflight(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Repository work"
        )
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("ordinary_play_invocation"),
                payload={"onboarding": {"classify_ns": 1}},
                guards={},
            ),
        ).session

        exited = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("conversation"),
                payload={"reason": "repository work"},
                guards={},
            ),
        )
        self.assertEqual("exited", exited.session.cursor.state)

    def test_advance_until_yield_executes_lexical_invocation_without_model(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1",
            task_key="task-1",
            request_original="Refactor the repository controller",
        )

        yielded = advance_until_yield(self.runtime, session, root=ROOT)

        self.assertEqual("qualify", yielded.projection["state"]["id"])
        self.assertEqual("evaluator_action", yielded.projection["state"]["boundary"])
        self.assertEqual(1, len(yielded.trace))
        self.assertEqual("classify_play_invocation", yielded.trace[0].action)
        self.assertEqual("ordinary_play_invocation", yielded.trace[0].event)

    def test_advance_until_yield_accepts_boundary_on_action_limit(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Repository work"
        )

        yielded = advance_until_yield(self.runtime, session, root=ROOT, max_actions=1)

        self.assertEqual("qualify", yielded.projection["state"]["id"])

    def test_advance_until_yield_auto_presents_context_backed_results(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Search Plays"
        )
        context = dict(session.context)
        context["state"] = "search_present"
        context["search"] = {
            "complete": True,
            "query": "release notes",
            "sources": ["local", "registry"],
            "result_refs": [],
            "results": [],
            "play_choices": [],
        }
        projected = session.__class__(
            schema=session.schema,
            cursor=replace(session.cursor, state=StateId("search_present")),
            context=context,
            preflight_ready=True,
        )

        yielded = advance_until_yield(self.runtime, projected, root=ROOT)

        self.assertEqual("search_offer", yielded.projection["state"]["id"])
        self.assertEqual("prompt", yielded.projection["state"]["boundary"])
        self.assertEqual("present_search_results", yielded.trace[0].action)
        self.assertEqual("search_presented", yielded.trace[0].event)
        self.assertEqual(1, len(yielded.presentations))
        self.assertIn("Search: `release notes`", yielded.presentations[0])

    def test_session_applies_consent_mutation_before_explore(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Explore a result"
        )
        context = dict(session.context)
        context["state"] = "explore_offer"
        projected = session.__class__(
            schema=session.schema,
            cursor=replace(session.cursor, state=StateId("explore_offer")),
            context=context,
            preflight_ready=True,
        )

        advanced = self.runtime.advance_session(
            projected,
            ControllerEvent(
                id=EventId("explore_approved"),
                payload={"prompt_version": "1", "selected_at": "2026-08-07T00:00:00Z"},
                guards={},
            ),
        )

        self.assertEqual("explore_welcome", advanced.session.cursor.state)
        self.assertEqual("approved", advanced.session.context["consent"]["explore"])
        self.assertEqual("explore", advanced.session.context["mode"])

    def test_session_maps_onboarding_starter_into_use_reference(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="$play"
        )
        context = dict(session.context)
        context["state"] = "onboarding_first_offer"
        context["onboarding"] = dict(context["onboarding"])
        context["onboarding"]["orientation_status"] = "recorded"
        context["onboarding"]["starter_reference"] = "modiqo/hello@0.1.0"
        projected = session.__class__(
            schema=session.schema,
            cursor=replace(session.cursor, state=StateId("onboarding_first_offer")),
            context=context,
            preflight_ready=False,
        )

        advanced = self.runtime.advance_session(
            projected,
            ControllerEvent(
                id=EventId("onboarding_starter_selected"),
                payload={
                    "prompt_version": "1",
                    "selected_at": "2026-08-07T00:00:00Z",
                    "onboarding": {"starter_reference": "modiqo/hello@0.1.0"},
                },
                guards={},
            ),
        )

        self.assertEqual("use_inspect", advanced.session.cursor.state)
        self.assertEqual("modiqo/hello@0.1.0", advanced.session.context["match"]["reference"])
        self.assertEqual("selected", advanced.session.context["onboarding"]["starter_status"])

    def test_session_derives_onboarding_guards_from_context(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="$play"
        )
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("empty_play_invocation"),
                payload={"onboarding": {"intent": "greeting", "classify_ns": 1}},
                guards={},
            ),
        ).session

        advanced = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("rote_available"),
                payload={
                    "onboarding": {
                        "rote_status": "installed",
                        "rote_command": "/tmp/rote",
                        "rote_off_path": False,
                        "probe_ns": 1,
                    }
                },
                guards={GuardId("onboarding_is_play_uri"): True},
            ),
        )

        self.assertEqual("onboarding_identity", advanced.session.cursor.state)

    def test_session_binds_uri_before_onboarding_probe_routes_to_inspection(self) -> None:
        uri = "https://play.modiqo.ai/modiqo/hello"
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original=uri
        )
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("play_uri_invocation"),
                payload={
                    "onboarding": {"intent": "play_uri", "play_uri": uri, "classify_ns": 1},
                    "match": {"reference": uri},
                },
                guards={},
            ),
        ).session
        advanced = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("rote_available"),
                payload={
                    "onboarding": {
                        "rote_status": "installed",
                        "rote_command": "/tmp/rote",
                        "rote_off_path": False,
                        "probe_ns": 1,
                    }
                },
                guards={},
            ),
        )

        self.assertEqual("use_inspect", advanced.session.cursor.state)
        self.assertEqual(uri, advanced.session.context["match"]["reference"])

    def test_advance_until_yield_builds_a_content_bound_receipt(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Run a Play"
        )
        context = dict(session.context)
        context["state"] = "use_receipt"
        context["match"] = dict(context["match"])
        context["match"]["reference"] = "modiqo/hello@0.1.0"
        context["evidence"] = dict(context["evidence"])
        context["evidence"]["verification"] = "verify:1"
        context["output"] = dict(context["output"])
        context["output"]["source"] = "rote_human_presentation"
        context["output"]["format"] = "markdown"
        context["output"]["primary"] = "# Hello\n\nunchanged"
        projected = session.__class__(
            schema=session.schema,
            cursor=replace(session.cursor, state=StateId("use_receipt")),
            context=context,
            preflight_ready=True,
        )

        yielded = advance_until_yield(self.runtime, projected, root=ROOT)

        self.assertEqual("receipt", yielded.projection["state"]["id"])
        self.assertEqual("terminal", yielded.projection["state"]["boundary"])
        self.assertEqual("build_receipt", yielded.trace[0].action)
        self.assertTrue(yielded.session.context["receipt_ref"].startswith("sha256:"))
        self.assertEqual(("# Hello\n\nunchanged",), yielded.presentations)
        self.assertEqual(
            len("# Hello\n\nunchanged".encode()),
            yielded.session.context["output"]["primary_bytes"],
        )

    def test_receipt_returns_structured_primary_to_the_harness_unchanged(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-json", task_key="task-json", request_original="Run a Play"
        )
        primary = {"z": 1, "rows": [{"name": "hello", "ok": True}]}
        context = dict(session.context)
        context["state"] = "use_receipt"
        context["match"] = dict(context["match"])
        context["match"]["reference"] = "modiqo/hello@0.1.0"
        context["evidence"] = dict(context["evidence"])
        context["evidence"]["verification"] = "verify:json"
        context["output"] = dict(context["output"])
        context["output"]["source"] = "structured_responses"
        context["output"]["format"] = "json"
        context["output"]["primary"] = primary
        projected = session.__class__(
            schema=session.schema,
            cursor=replace(session.cursor, state=StateId("use_receipt")),
            context=context,
            preflight_ready=True,
        )

        yielded = advance_until_yield(self.runtime, projected, root=ROOT)

        self.assertEqual((primary,), yielded.presentations)
        self.assertEqual(primary, yielded.session.context["output"]["primary"])

    @patch("play.runtime_actions.subprocess.run")
    def test_failed_deterministic_command_surfaces_stderr_without_json_debugging(
        self, run
    ) -> None:
        run.return_value.returncode = 1
        run.return_value.stdout = ""
        run.return_value.stderr = "requested outcome is missing"
        session = self.runtime.initial_session(
            run_id="session-failure",
            task_key="task-failure",
            request_original="$play",
        )

        yielded = advance_until_yield(self.runtime, session, root=ROOT)

        self.assertEqual("blocked", yielded.projection["state"]["id"])
        self.assertEqual(("requested outcome is missing",), yielded.presentations)
        self.assertEqual("action_blocked", yielded.trace[0].event)

    @patch("play.runtime_actions.subprocess.run")
    def test_advance_until_yield_auto_inspects_and_routes_local_play(self, run) -> None:
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = json.dumps(
            {
                "schema": "play.run-disclosure/v1",
                "complete": True,
                "exact_reference": "modiqo/hello@0.1.0",
                "description": "Hello",
                "local_change": "none",
                "dependencies": {"adapter_checks": []},
                "operations": [],
                "effects": {"summary": "No declared writes."},
                "blockers": [],
                "disclosure_sha256": "a" * 64,
                "identity": {
                    "name": "hello",
                    "description": "Hello",
                    "visibility": "public",
                },
                "parameters": [],
                "preflight": {
                    "run_eligible": True,
                    "play_local_state": "exact_ready",
                    "decision": "ready",
                    "blockers": [],
                },
                "approval": {"notice": "Nothing has run."},
            }
        )
        run.side_effect = [
            run.return_value,
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "schema": "play.run-handoff-preparation/v1",
                        "ok": True,
                        "event": "play_run_handoff_ready",
                        "auth_repair": {
                            "original_packet": {"schema": "play.run-handoff/v1"},
                            "original_packet_sha256": "c" * 64,
                        },
                    }
                ),
            ),
        ]
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Run Hello"
        )
        context = dict(session.context)
        context["state"] = "use_inspect"
        context["mode"] = "use"
        context["match"] = dict(context["match"])
        context["match"]["reference"] = "modiqo/hello"
        projected = session.__class__(
            schema=session.schema,
            cursor=replace(session.cursor, state=StateId("use_inspect")),
            context=context,
            preflight_ready=True,
        )

        yielded = advance_until_yield(self.runtime, projected, root=ROOT)

        self.assertEqual("use_run", yielded.projection["state"]["id"])
        self.assertEqual("deterministic_action", yielded.projection["state"]["boundary"])
        self.assertEqual("inspect_registry_play", yielded.trace[0].action)
        self.assertEqual("play_inspected", yielded.trace[0].event)
        self.assertEqual("route_inspected_play", yielded.trace[1].action)
        self.assertEqual("local_play_ready", yielded.trace[1].event)
        self.assertEqual("prepare_play_run_handoff", yielded.trace[2].action)
        self.assertEqual("play_run_handoff_ready", yielded.trace[2].event)
        self.assertEqual(1, len(yielded.presentations))
        self.assertIn("#", yielded.presentations[0])

    @patch("play.runtime_actions.subprocess.run")
    def test_deterministic_match_presents_remote_choices_before_pull_consent(self, run) -> None:
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = json.dumps(
            {
                "complete": True,
                "exact_reference": "modiqo/retrieve-rideshare-receipts@0.0.5",
                "description": "Retrieve rideshare receipts",
                "local_change": "install",
                "dependencies": {"adapter_checks": []},
                "operations": [],
                "effects": {"summary": "No declared writes."},
                "blockers": [],
                "disclosure_sha256": "b" * 64,
                "identity": {
                    "name": "retrieve-rideshare-receipts",
                    "description": "Retrieve rideshare receipts",
                    "visibility": "private",
                },
                "parameters": [],
                "preflight": {
                    "run_eligible": True,
                    "play_local_state": "missing",
                    "decision": "install_required",
                    "blockers": [],
                },
                "approval": {"notice": "Nothing has been pulled or run."},
            }
        )
        session = self.runtime.initial_session(
            run_id="session-search",
            task_key="task-search",
            request_original="fetch rideshare receipts for July 2026",
        )
        context = dict(session.context)
        context["state"] = "classify"
        context["mode"] = "use"
        context["request"] = dict(context["request"])
        context["request"]["intent"] = "fetch rideshare receipts for july 2026"
        context["request"]["requested_outcome"] = "rideshare receipts"
        candidate = {
            "name": "retrieve-rideshare-receipts",
            "description": "Retrieve rideshare receipts" + " safely" * 50,
            "reference": "modiqo/retrieve-rideshare-receipts@0.0.5",
            "exact_reference": "modiqo/retrieve-rideshare-receipts@0.0.5",
            "version": "0.0.5",
            "status": "approved",
            "sources": ["remote_private", "remote_public"],
            "score": 1.0,
            "coverage": 1.0,
            "match_classification": "full",
            "primary_scope": "remote_private",
            "uri": "https://play.modiqo.ai/modiqo/retrieve-rideshare-receipts@0.0.5",
            "run_command": "rote play run modiqo/retrieve-rideshare-receipts@0.0.5",
            "inspect_command": "rote play inspect modiqo/retrieve-rideshare-receipts@0.0.5 --json",
            "hint_kind": "play",
            "local_availability": "not_found",
            "execution_resolution": "pull_required",
            "selection_description": "Remote private match; pulling requires approval.",
        }
        context["search"] = {
            "complete": True,
            "query": context["request"]["intent"],
            "sources": ["local", "remote_private", "remote_public"],
            "result_refs": [candidate["reference"]],
            "results": [candidate] * 5,
            "play_choices": [
                {
                    "reference": candidate["reference"],
                    "label": "retrieve-rideshare-receipts — modiqo",
                    "description": candidate["selection_description"],
                    "parameters": {},
                }
            ],
        }
        projected = session.__class__(
            schema=session.schema,
            cursor=replace(session.cursor, state=StateId("classify")),
            context=context,
            preflight_ready=True,
        )
        token_before = len(encode_session(projected))

        yielded = advance_until_yield(self.runtime, projected, root=ROOT)

        self.assertEqual("search_offer", yielded.projection["state"]["id"])
        self.assertEqual("prompt", yielded.projection["state"]["boundary"])
        self.assertEqual(
            ["classify_adequacy", "present_search_results"],
            [item.action for item in yielded.trace],
        )
        self.assertTrue(yielded.session.context["search"]["results"])
        self.assertTrue(yielded.session.context["search"]["play_choices"])
        self.assertLess(len(encode_session(yielded.session)), token_before + 512)

    @patch("play.runtime_actions.subprocess.run")
    def test_advance_until_yield_collects_and_presents_awareness(self, run) -> None:
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = json.dumps(
            {
                "complete": True,
                "window": {"start": "2026-08-06", "end": "2026-08-07"},
                "organizations": [],
                "org_updates": {"new": [], "revised": [], "revised_complete": True},
                "public_top": [],
                "public_groups": [],
                "ranking": {
                    "label": "Authorized public Plays by lifetime downloads",
                    "complete": True,
                },
                "personal_stats": {"reason": "verified run counts unavailable"},
                "memory": {"status": "changed"},
            }
        )
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="What's new?"
        )
        context = dict(session.context)
        context["state"] = "awareness_collect"
        context["mode"] = "awareness"
        projected = session.__class__(
            schema=session.schema,
            cursor=replace(session.cursor, state=StateId("awareness_collect")),
            context=context,
            preflight_ready=True,
        )

        yielded = advance_until_yield(self.runtime, projected, root=ROOT)

        self.assertEqual("awareness_offer", yielded.projection["state"]["id"])
        self.assertEqual("prompt", yielded.projection["state"]["boundary"])
        self.assertEqual(
            ["collect_awareness_digest", "present_awareness_digest"],
            [item.action for item in yielded.trace],
        )
        self.assertEqual(1, len(yielded.presentations))
        self.assertIn("What’s new in Plays", yielded.presentations[0])

    def test_session_completes_the_use_contract_without_model_owned_context(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-use", task_key="task-use", request_original="Run Hello"
        )
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("ordinary_play_invocation"),
                payload={"onboarding": {"classify_ns": 1}},
                guards={},
            ),
        ).session
        session = self.runtime.confirm_preflight(
            session, {"schema": "play.preflight/v1", "ready": True}
        )
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("exact_play_request"),
                payload={
                    "request": {
                        "intent": "run hello",
                        "requested_outcome": "hello result",
                        "parameters": {},
                    },
                    "match": {"reference": "modiqo/hello"},
                    "modality_policy": session.context["modality_policy"],
                },
                guards={},
            ),
        ).session
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("play_inspected"),
                payload={
                    "inspection": {
                        "complete": True,
                        "exact_reference": "modiqo/hello@0.1.0",
                        "description": "Hello",
                        "local_change": "none",
                        "dependencies": {},
                        "operations": [],
                        "effects": {},
                        "disclosure_sha256": "a" * 64,
                    }
                },
                guards={},
            ),
        ).session
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("local_play_ready"),
                payload={},
                guards={},
            ),
        ).session
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("play_run_handoff_ready"),
                payload={
                    "auth_repair": {
                        "original_packet": {"schema": "play.run-handoff/v1"},
                        "original_packet_sha256": "c" * 64,
                    }
                },
                guards={},
            ),
        ).session
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("play_run_ready"),
                payload={
                    "play": {"version": "0.1.0"},
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
                        "primary": "# Hello",
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
        ).session
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("outcome_verified"),
                payload={"postconditions": ["hello returned"], "evidence_refs": ["verify:1"]},
                guards={},
            ),
        ).session

        yielded = advance_until_yield(self.runtime, session, root=ROOT)

        self.assertEqual("receipt", yielded.projection["state"]["id"])
        self.assertEqual("verify:1", yielded.session.context["evidence"]["verification"])
        self.assertTrue(yielded.session.context["receipt_ref"].startswith("sha256:"))

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

    def test_complete_run_output_passes_unchanged_to_verification(self) -> None:
        run_cursor = replace(self.cursor(), state=StateId("use_run"))
        verify_cursor = self.runtime.step(
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
        self.assertEqual("adapter_converge", handoff_cursor.state)

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

    def test_public_owner_guard_is_derived_before_release(self) -> None:
        save_cursor = replace(self.cursor(), state=StateId("save_offer"))
        resolved = self.runtime.step(
            save_cursor,
            ControllerEvent(
                id=EventId("save_public"),
                payload={
                    "prompt_version": "1",
                    "selected_at": "2026-08-07T00:00:00Z",
                    "publication": {
                        "owner_resolution": "resolved",
                        "owner": "chetanconikee",
                    },
                },
                guards={GuardId("public_owner_is_resolved"): False},
            ),
        )
        self.assertEqual("author_release", resolved.cursor.state)

        choice = self.runtime.step(
            save_cursor,
            ControllerEvent(
                id=EventId("save_public"),
                payload={
                    "prompt_version": "1",
                    "selected_at": "2026-08-07T00:00:00Z",
                    "publication": {
                        "owner_resolution": "choice_required",
                        "owner": None,
                    },
                },
                guards={GuardId("public_owner_is_resolved"): True},
            ),
        )
        self.assertEqual("public_owner_offer", choice.cursor.state)

        unavailable = self.runtime.step(
            save_cursor,
            ControllerEvent(
                id=EventId("save_public"),
                payload={
                    "prompt_version": "1",
                    "selected_at": "2026-08-07T00:00:00Z",
                    "publication": {
                        "owner_resolution": "unavailable",
                        "owner": "spoofed",
                    },
                },
                guards={
                    GuardId("public_owner_is_resolved"): True,
                    GuardId("public_owner_choice_is_required"): True,
                },
            ),
        )
        self.assertEqual("blocked", unavailable.cursor.state)

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
                    "reason": "registry Play published before birth_capture",
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
