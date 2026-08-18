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
from play.runtime_actions import _execute_instruction, advance_until_yield
from play.runtime_context import RuntimeContextError, validate_mutation_contract
from play.handoff import prepare_play_run_handoff


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
                payload={"onboarding": {"classify_ns": 1}, "preferences": {"policies": []}},
                guards={},
            ),
        ).cursor

    def initial_cursor(self):
        return self.runtime.initial_cursor(run_id="run-1", task_key="task-1")

    def test_compiles_the_authoritative_bundle(self) -> None:
        self.assertEqual("invoke", self.runtime.bundle.initial)
        self.assertEqual(73, len(self.runtime.bundle.states))
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
        self.assertEqual("runtime", projection["state"]["boundary"])
        self.assertEqual("runtime", projection["instruction"]["executor"])
        self.assertEqual("classify_play_invocation", projection["instruction"]["id"])
        self.assertIn("ordinary_play_invocation", projection["accepted_events"])
        self.assertNotIn("qualify_request", str(projection))

    def test_advance_returns_the_next_compact_instruction(self) -> None:
        result = self.runtime.advance(
            self.initial_cursor(),
            ControllerEvent(
                id=EventId("ordinary_play_invocation"),
                payload={"onboarding": {"classify_ns": 1}, "preferences": {"policies": []}},
                guards={},
            ),
        ).as_dict()

        self.assertEqual("play.runtime-advance/v1", result["schema"])
        self.assertEqual("qualify", result["projection"]["state"]["id"])
        self.assertEqual("model", result["projection"]["state"]["boundary"])
        self.assertEqual("qualify_request", result["projection"]["instruction"]["id"])
        self.assertNotIn("preflight", str(result["projection"]["instruction"]))

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
            ("use_authentication_execute", "rote-adapter-config"),
            ("onboarding_team_create", "rote-org"),
            ("crystallize", "rote-flow-crystallization"),
            ("author_release", "rote-flow-authoring"),
        ):
            projection = self.runtime.project(
                replace(session.cursor, state=StateId(state)), session.context
            ).as_dict()
            self.assertEqual(expected, projection["instruction"]["specialist"])

    def test_prompt_event_template_prebinds_controller_evidence(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-template",
            task_key="task-template",
            request_original="Run remote Hello",
        )
        context = dict(session.context)
        context["state"] = "use_offer"
        context["inspection"] = dict(context["inspection"])
        context["inspection"].update(
            {
                "exact_reference": "modiqo/hello@0.1.0",
                "disclosure_sha256": "d" * 64,
            }
        )
        context["request"] = dict(context["request"])
        context["request"]["parameters"] = {"region": "us"}

        projection = self.runtime.project(
            replace(session.cursor, state=StateId("use_offer")), context
        ).as_dict()
        template = projection["accepted_events"]["play_run_approved"]["event_template"]

        self.assertEqual("human", projection["state"]["boundary"])
        self.assertEqual("play_run_approved", template["id"])
        self.assertIsNone(template["payload"]["prompt_version"])
        self.assertEqual(
            "modiqo/hello@0.1.0",
            template["payload"]["inspection"]["exact_reference"],
        )
        self.assertEqual("d" * 64, template["payload"]["inspection"]["disclosure_sha256"])
        self.assertEqual({"region": "us"}, template["payload"]["request"]["parameters"])

    def test_session_initializes_complete_valid_context(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1",
            task_key="task-1",
            request_original="Find a Play for release notes",
        )

        self.assertEqual("play.context/v1", session.context["schema"])
        self.assertEqual("invoke", session.context["state"])
        self.assertEqual("detailed", session.context["output_policy"]["mode"])
        self.assertIsNone(session.context["authentication"]["source"])
        self.assertEqual("unknown", session.context["candidate"]["publication_status"])
        projection = self.runtime.project_session(session).as_dict()
        self.assertEqual(
            {"request": {"original": "Find a Play for release notes"}},
            projection["instruction"]["input"],
        )

    def test_play_auth_failure_preserves_source_for_guided_authentication(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-auth-source",
            task_key="task-auth-source",
            request_original="Run the Crucible landing-page assessment",
        )
        context = dict(session.context)
        context["state"] = "use_run"
        context["match"] = {
            **context["match"],
            "reference": "crucible-heavybit/landing-page-assessment",
        }
        context["inspection"] = {
            **context["inspection"],
            "exact_reference": "crucible-heavybit/landing-page-assessment@0.2.0",
            "disclosure_sha256": "a" * 64,
        }
        context["authentication"] = {
            **context["authentication"],
            "original_packet": {"schema": "play.run-handoff/v1"},
            "original_packet_sha256": "b" * 64,
        }
        bound = replace(
            session,
            cursor=replace(session.cursor, state=StateId("use_run")),
            context=context,
        )

        advanced = self.runtime.advance_session(
            bound,
            ControllerEvent(
                id=EventId("play_authentication_required"),
                payload={
                    "authentication": {
                        "source": "rote_authentication_required",
                        "owner": "rote-adapter-config",
                        "recoverable": True,
                        "adapter_id": "crucible",
                        "env_var": "ADAPTER_CRUCIBLE_TOKEN",
                        "classified_rung": "oauth_dcr",
                        "distinguishing_error": "missing: browser authorization required",
                        "evidence_refs": ["sha256:auth-required"],
                    }
                },
                guards={},
            ),
        )

        self.assertEqual("use_authentication_offer", advanced.session.context["state"])
        self.assertEqual(
            "rote_authentication_required",
            advanced.session.context["authentication"]["source"],
        )
        self.assertEqual("required", advanced.session.context["authentication"]["status"])
        self.assertEqual("human", advanced.projection.as_dict()["state"]["boundary"])
        question = advanced.projection.as_dict()["instruction"]["question"]
        self.assertIn("crucible authentication blocked", question)
        self.assertIn("rote token set ADAPTER_CRUCIBLE_TOKEN --stdin", question)
        self.assertIn("never ask for the token in chat", question)
        authentication_choice = next(
            choice
            for choice in advanced.projection.as_dict()["instruction"]["choices"]
            if choice["id"] == "authenticate"
        )
        self.assertIn("static credentials stay outside the harness", authentication_choice["description"])

    def test_approved_authentication_redirects_harness_to_adapter_specialist(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-auth-redirect",
            task_key="task-auth-redirect",
            request_original="Run the Crucible landing-page assessment",
        )
        prepared = prepare_play_run_handoff(
            {
                "run_id": "session-auth-redirect",
                "request": {
                    "requested_outcome": "Assess https://www.modiqo.ai",
                    "parameters": {"source": "https://www.modiqo.ai"},
                },
                "inspection": {
                    "exact_reference": "crucible-heavybit/landing-page-assessment@0.2.0",
                    "disclosure_sha256": "a" * 64,
                },
            }
        )
        context = dict(session.context)
        context["state"] = "use_authentication_offer"
        context["request"] = {
            **context["request"],
            "requested_outcome": "Assess https://www.modiqo.ai",
        }
        context["match"] = {
            **context["match"],
            "reference": "crucible-heavybit/landing-page-assessment",
        }
        context["authentication"] = {
            **context["authentication"],
            "source": "rote_authentication_required",
            "status": "required",
            "owner": "rote-adapter-config",
            "recoverable": True,
            "adapter_id": "crucible",
            "env_var": "ADAPTER_CRUCIBLE_TOKEN",
            "classified_rung": "oauth_dcr",
            "distinguishing_error": "missing: browser authorization required",
            "original_packet": prepared["authentication"]["original_packet"],
            "original_packet_sha256": prepared["authentication"][
                "original_packet_sha256"
            ],
            "evidence_refs": ["sha256:auth-required"],
        }
        bound = replace(
            session,
            cursor=replace(session.cursor, state=StateId("use_authentication_offer")),
            context=context,
        )
        approved = self.runtime.advance_session(
            bound,
            ControllerEvent(
                id=EventId("authentication_approved"),
                payload={
                    "prompt_version": "approve_authentication/v1",
                    "selected_at": "2026-08-15T23:59:00-07:00",
                    "authentication": {
                        "adapter_id": "crucible",
                        "env_var": "ADAPTER_CRUCIBLE_TOKEN",
                        "classified_rung": "oauth_dcr",
                        "distinguishing_error": "missing: browser authorization required",
                        "original_packet_sha256": prepared["authentication"][
                            "original_packet_sha256"
                        ],
                    },
                },
                guards={},
            ),
        )

        yielded = advance_until_yield(self.runtime, approved.session, root=ROOT)

        self.assertEqual("use_authentication_execute", yielded.projection["state"]["id"])
        self.assertEqual("specialist", yielded.projection["state"]["boundary"])
        self.assertEqual(
            "rote-adapter-config", yielded.projection["instruction"]["specialist"]
        )
        authentication_policy = " ".join(yielded.projection["instruction"]["command_policy"])
        self.assertIn("out-of-band setup path", authentication_policy)
        self.assertIn("first-party HTTPS token_url", authentication_policy)
        self.assertIn("rote token set <env_var> --stdin", authentication_policy)
        self.assertEqual([], yielded.projection["instruction"]["input"]["inspection"]["operations"])

        evidence_refs = ["rote:adapter-health/crucible:fresh"]
        specialist_result = {
            "source": "google_oauth_result",
            "status": "ready",
            "adapter_id": "crucible",
            "env_var": "ADAPTER_CRUCIBLE_TOKEN",
            "classified_rung": "oauth_dcr",
            "recoverable": True,
            "blocked_reason": None,
            "distinguishing_error": "missing: browser authorization required",
            "authentication_action": "reauth",
            "evidence_refs": evidence_refs,
        }
        received = self.runtime.advance_session(
            yielded.session,
            ControllerEvent(
                id=EventId("authentication_ready"),
                payload={"authentication": specialist_result},
                guards={},
            ),
        )

        self.assertEqual("use_inspect", received.session.context["state"])
        result = received.session.context["authentication"]
        self.assertEqual("authenticated", result["status"])
        self.assertEqual("crucible", result["adapter_id"])
        self.assertEqual("reauth", result["authentication_action"])
        self.assertEqual(evidence_refs, result["evidence_refs"])
        self.assertIsNone(result["receipt"])

    def test_session_advance_applies_event_and_checkpoints_context(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Repository work"
        )
        advanced = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("ordinary_play_invocation"),
                payload={"onboarding": {"classify_ns": 42}, "preferences": {"policies": []}},
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
            {
                "request": {"original": "Repository work"},
                "preferences": {"policies": []},
            },
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

    def test_session_advances_play_trajectory_without_global_preflight(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Find release notes"
        )
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("ordinary_play_invocation"),
                payload={"onboarding": {"classify_ns": 1}, "preferences": {"policies": []}},
                guards={},
            ),
        ).session
        event = ControllerEvent(
            id=EventId("outcome_request"),
            payload={
                "request": {"intent": "release notes", "requested_outcome": "notes"},
                "modality_policy": session.context["modality_policy"],
                "capture": {
                    "decision": "normal",
                    "reason": "one bounded lookup",
                    "task_class": "data-fetch-report",
                },
            },
            guards={},
        )

        advanced = self.runtime.advance_session(session, event)
        self.assertEqual("search", advanced.session.cursor.state)

    def test_explicit_awareness_enters_digest_without_model_or_preflight(self) -> None:
        session = self.runtime.initial_session(
            run_id="awareness-fast", task_key="play-whats-new", request_original="$play what's new"
        )
        advanced = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("play_awareness_invocation"),
                payload={
                    "request": {"intent": "what's new"},
                    "awareness": {"window_days": 7},
                    "preferences": {"policies": []},
                    "onboarding": {"classify_ns": 1},
                },
                guards={},
            ),
        )
        self.assertEqual("awareness_collect", advanced.session.cursor.state)
        self.assertFalse(advanced.session.preflight_ready)

    def test_session_exit_does_not_require_preflight(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="Repository work"
        )
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("ordinary_play_invocation"),
                payload={"onboarding": {"classify_ns": 1}, "preferences": {"policies": []}},
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
        self.assertEqual("model", yielded.projection["state"]["boundary"])
        self.assertEqual(1, len(yielded.trace))
        self.assertEqual("classify_play_invocation", yielded.trace[0].action)
        self.assertEqual("ordinary_play_invocation", yielded.trace[0].event)

    @patch("play.runtime_actions.subprocess.run")
    def test_retrieve_outcome_inspects_full_remote_match_without_choice(
        self, run
    ) -> None:
        candidate = {
            "name": "retrieve-rideshare-receipts",
            "description": "Retrieve rideshare receipts",
            "reference": "modiqo/retrieve-rideshare-receipts@0.1.0",
            "exact_reference": "modiqo/retrieve-rideshare-receipts@0.1.0",
            "version": "0.1.0",
            "status": "approved",
            "sources": ["remote_public"],
            "score": 1.0,
            "coverage": 1.0,
            "match_classification": "full",
            "matched_adapters": ["gmail"],
            "labels": ["Workplace"],
            "tags": ["job-expense-reconciliation", "tool-gmail"],
            "primary_scope": "remote_public",
            "uri": "https://play.modiqo.ai/modiqo/retrieve-rideshare-receipts@0.1.0",
            "run_command": "unused",
            "inspect_command": "unused",
            "hint_kind": "play",
            "local_availability": "not_found",
            "execution_resolution": "pull_required",
            "selection_description": "Remote public match; pulling requires approval.",
        }
        run.side_effect = [
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "invocation_kind": "outcome",
                        "intent": "retrieve rideshare receipts",
                        "classify_ns": 1,
                    }
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "complete": True,
                        "query": "retrieve rideshare receipts",
                        "sources": ["local", "remote_private", "remote_public"],
                        "result_refs": [candidate["reference"]],
                        "results": [candidate],
                        "play_choices": [
                            {
                                "reference": candidate["reference"],
                                "label": "retrieve-rideshare-receipts — public",
                                "description": candidate["selection_description"],
                                "parameters": {},
                            }
                        ],
                    }
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "complete": True,
                        "exact_reference": candidate["exact_reference"],
                        "description": candidate["description"],
                        "identity": {
                            "name": candidate["name"],
                            "description": candidate["description"],
                            "visibility": "public",
                        },
                        "parameters": [
                            {
                                "name": "start_date",
                                "label": "Start date",
                                "type": "string",
                                "required": True,
                                "description": "Inclusive date in YYYY-MM-DD format",
                                "example": "2026-07-01",
                                "has_default": False,
                                "default": None,
                            },
                            {
                                "name": "end_date",
                                "label": "End date",
                                "type": "string",
                                "required": True,
                                "description": "Exclusive date in YYYY-MM-DD format",
                                "example": "2026-09-01",
                                "has_default": False,
                                "default": None,
                            },
                        ],
                        "local_change": "install",
                        "dependencies": {"adapter_checks": []},
                        "operations": [],
                        "effects": {"summary": "No declared writes."},
                        "blockers": [],
                        "disclosure_sha256": "a" * 64,
                        "preflight": {
                            "run_eligible": True,
                            "play_local_state": "missing",
                            "decision": "install_required",
                            "blockers": [],
                        },
                        "approval": {"notice": "Nothing has run."},
                    }
                ),
            ),
        ]
        session = self.runtime.initial_session(
            run_id="rideshare-fast-path",
            task_key="rideshare-fast-path",
            request_original="retrieve rideshare receipts between July and August 2026",
        )

        yielded = advance_until_yield(self.runtime, session, root=ROOT)

        self.assertEqual("use_decide", yielded.projection["state"]["id"])
        self.assertEqual("model", yielded.projection["state"]["boundary"])
        self.assertEqual(
            [
                "classify_play_invocation",
                "search_authorized_plays",
                "classify_adequacy",
                "inspect_registry_play",
            ],
            [item.action for item in yielded.trace],
        )
        instruction = yielded.projection["instruction"]
        self.assertEqual("route_inspected_play", instruction["id"])
        self.assertEqual(
            "retrieve rideshare receipts between July and August 2026",
            instruction["input"]["request"]["original"],
        )
        self.assertEqual(2, len(instruction["input"]["inspection"]["parameters"]))
        self.assertNotIn("qualify_request", str(yielded.projection))
        self.assertNotIn("Which matching Play", "\n".join(yielded.presentations))

        normalized = self.runtime.advance_session(
            yielded.session,
            ControllerEvent(
                id=EventId("remote_pull_required"),
                payload={
                    "request": {
                        "parameters": {
                            "start_date": "2026-07-01",
                            "end_date": "2026-09-01",
                        }
                    }
                },
                guards={},
            ),
        ).session
        approval = advance_until_yield(self.runtime, normalized, root=ROOT)
        self.assertEqual("use_offer", approval.projection["state"]["id"])
        self.assertEqual("human", approval.projection["state"]["boundary"])
        self.assertEqual(
            {"start_date": "2026-07-01", "end_date": "2026-09-01"},
            approval.session.context["request"]["parameters"],
        )

    @patch("play.runtime_actions.subprocess.run")
    def test_uri_collects_missing_required_parameters_before_pull_consent(
        self, run
    ) -> None:
        uri = "https://play.modiqo.ai/modiqo/retrieve-rideshare-receipts"
        disclosure = {
            "complete": True,
            "exact_reference": "modiqo/retrieve-rideshare-receipts@0.1.0",
            "description": "Retrieve rideshare receipts",
            "identity": {
                "name": "retrieve-rideshare-receipts",
                "description": "Retrieve rideshare receipts",
                "visibility": "public",
            },
            "parameters": [
                {
                    "name": "start_date",
                    "label": "Start date",
                    "type": "string",
                    "required": True,
                    "description": "Inclusive YYYY-MM-DD date",
                    "has_default": False,
                    "default": None,
                },
                {
                    "name": "end_date",
                    "label": "End date",
                    "type": "string",
                    "required": True,
                    "description": "Inclusive YYYY-MM-DD date",
                    "has_default": False,
                    "default": None,
                },
            ],
            "local_change": "install",
            "dependencies": {"adapter_checks": []},
            "operations": [],
            "effects": {"summary": "No declared writes."},
            "blockers": [],
            "disclosure_sha256": "a" * 64,
            "preflight": {
                "run_eligible": True,
                "play_local_state": "missing",
                "decision": "install_required",
                "blockers": [],
            },
            "approval": {"notice": "Nothing has run."},
        }
        run.side_effect = [
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "invocation_kind": "play_uri",
                        "play_uri": uri,
                        "parameters": {},
                        "classify_ns": 1,
                    }
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {"rote_status": "installed", "rote_command": "/usr/bin/rote"}
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "identity_status": "authenticated",
                        "email": "friend@example.com",
                        "email_handle": "friend",
                        "identity_ref": "sha256:" + "b" * 64,
                        "whoami_ns": 1,
                    }
                ),
            ),
            SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(disclosure)),
        ]
        session = self.runtime.initial_session(
            run_id="rideshare-parameters",
            task_key="rideshare-parameters",
            request_original=uri,
        )

        decision = advance_until_yield(self.runtime, session, root=ROOT)
        self.assertEqual("use_decide", decision.projection["state"]["id"])
        self.assertEqual("model", decision.projection["state"]["boundary"])

        requested_start = self.runtime.advance_session(
            decision.session,
            ControllerEvent(
                id=EventId("play_parameter_required"),
                payload={
                    "request": {"parameters": {}},
                    "parameter_input": {
                        "name": "start_date",
                        "label": "Start date",
                        "type": "string",
                        "description": "Inclusive YYYY-MM-DD date",
                    },
                },
                guards={},
            ),
        ).session
        first = advance_until_yield(self.runtime, requested_start, root=ROOT)
        self.assertEqual("use_parameter_offer", first.projection["state"]["id"])
        self.assertEqual("start_date", first.session.context["parameter_input"]["name"])
        self.assertEqual(
            "Expected: Inclusive YYYY-MM-DD date\n\n"
            "What value should I use for Start date?",
            first.projection["instruction"]["question"],
        )
        self.assertNotIn("template_fields", first.projection["instruction"])

        supplied_start = self.runtime.advance_session(
            first.session,
            ControllerEvent(
                id=EventId("play_parameter_supplied"),
                payload={
                    "prompt_version": "supply_play_parameter",
                    "selected_at": "2026-08-08T00:00:00Z",
                    "parameter_input": {
                        "name": "start_date",
                        "value": "2026-07-01",
                    },
                },
                guards={},
            ),
        ).session
        second_decision = advance_until_yield(self.runtime, supplied_start, root=ROOT)
        self.assertEqual("use_decide", second_decision.projection["state"]["id"])
        requested_end = self.runtime.advance_session(
            second_decision.session,
            ControllerEvent(
                id=EventId("play_parameter_required"),
                payload={
                    "request": {"parameters": {"start_date": "2026-07-01"}},
                    "parameter_input": {
                        "name": "end_date",
                        "label": "End date",
                        "type": "string",
                        "description": "Inclusive YYYY-MM-DD date",
                    },
                },
                guards={},
            ),
        ).session
        second = advance_until_yield(self.runtime, requested_end, root=ROOT)
        self.assertEqual("use_parameter_offer", second.projection["state"]["id"])
        self.assertEqual("end_date", second.session.context["parameter_input"]["name"])

        supplied_end = self.runtime.advance_session(
            second.session,
            ControllerEvent(
                id=EventId("play_parameter_supplied"),
                payload={
                    "prompt_version": "supply_play_parameter",
                    "selected_at": "2026-08-08T00:00:01Z",
                    "parameter_input": {
                        "name": "end_date",
                        "value": "2026-07-31",
                    },
                },
                guards={},
            ),
        ).session
        final_decision = advance_until_yield(self.runtime, supplied_end, root=ROOT)
        self.assertEqual("use_decide", final_decision.projection["state"]["id"])
        ready = self.runtime.advance_session(
            final_decision.session,
            ControllerEvent(
                id=EventId("remote_pull_required"),
                payload={
                    "request": {
                        "parameters": {
                            "start_date": "2026-07-01",
                            "end_date": "2026-07-31",
                        }
                    }
                },
                guards={},
            ),
        ).session
        consent = advance_until_yield(self.runtime, ready, root=ROOT)
        self.assertEqual("use_offer", consent.projection["state"]["id"])
        self.assertEqual(
            {"start_date": "2026-07-01", "end_date": "2026-07-31"},
            consent.session.context["request"]["parameters"],
        )

    def test_inspected_frontmatter_rejects_invented_repository_parameter(self) -> None:
        session = self.runtime.initial_session(
            run_id="committers-parameter-contract",
            task_key="committers-parameter-contract",
            request_original="list top committers for modiqo/rote",
        )
        context = dict(session.context)
        context["state"] = "use_decide"
        context["request"] = {
            **context["request"],
            "intent": "list top committers for modiqo/rote",
            "requested_outcome": "list top committers for modiqo/rote",
        }
        context["match"] = {
            **context["match"],
            "reference": "modiqo/list-top-committers",
        }
        context["inspection"] = {
            **context["inspection"],
            "complete": True,
            "exact_reference": "modiqo/list-top-committers@0.1.4",
            "local_change": "install",
            "disclosure_sha256": "a" * 64,
            "parameters": [
                {
                    "name": "owner",
                    "label": "Owner",
                    "type": "string",
                    "required": True,
                    "description": "GitHub repository owner",
                    "valid_values": [],
                },
                {
                    "name": "repo",
                    "label": "Repo",
                    "type": "string",
                    "required": True,
                    "description": "GitHub repository name",
                    "valid_values": [],
                },
                {
                    "name": "limit",
                    "label": "Limit",
                    "type": "integer",
                    "required": False,
                    "description": "Maximum contributors",
                    "valid_values": [],
                },
            ],
        }
        bound = replace(
            session,
            cursor=replace(session.cursor, state=StateId("use_decide")),
            context=context,
        )

        with self.assertRaisesRegex(
            ControllerRuntimeError,
            r"undeclared parameter\(s\): repository; declared parameters: owner, repo, limit",
        ):
            self.runtime.advance_session(
                bound,
                ControllerEvent(
                    id=EventId("remote_pull_required"),
                    payload={
                        "request": {"parameters": {"repository": "modiqo/rote"}}
                    },
                    guards={},
                ),
            )

        accepted = self.runtime.advance_session(
            bound,
            ControllerEvent(
                id=EventId("remote_pull_required"),
                payload={
                    "request": {
                        "parameters": {"owner": "modiqo", "repo": "rote"}
                    }
                },
                guards={},
            ),
        )
        self.assertEqual("use_offer", accepted.session.context["state"])
        self.assertEqual(
            {"owner": "modiqo", "repo": "rote"},
            accepted.session.context["request"]["parameters"],
        )

    @patch("play.runtime_actions.subprocess.run")
    def test_run_hello_resolves_empty_parameter_contract_then_executes(self, run) -> None:
        disclosure = {
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
        run.side_effect = [
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "schema": "play.onboarding/v1",
                        "kind": "invocation",
                        "ok": True,
                        "invocation_kind": "play_uri",
                        "play_uri": "https://play.modiqo.ai/modiqo/hello@0.1.0",
                        "classify_ns": 1,
                    }
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "schema": "play.onboarding/v1",
                        "kind": "rote_probe",
                        "ok": True,
                        "rote_status": "installed",
                        "rote_command": "/usr/local/bin/rote",
                        "rote_off_path": False,
                        "probe_ns": 1,
                    }
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "schema": "play.onboarding/v1",
                        "kind": "identity",
                        "ok": True,
                        "identity_status": "authenticated",
                        "email": "friend@example.com",
                        "email_handle": "friend",
                        "identity_ref": "sha256:" + "b" * 64,
                        "whoami_ns": 1,
                    }
                ),
            ),
            SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(disclosure)),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "schema": "play.run-handoff-preparation/v1",
                        "ok": True,
                        "event": "play_run_handoff_ready",
                        "authentication": {
                            "original_packet": {"schema": "play.run-handoff/v1"},
                            "original_packet_sha256": "c" * 64,
                        },
                    }
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "schema": "play.run-result/v1",
                        "ok": True,
                        "event": "play_run_ready",
                        "play": {"version": "0.1.0"},
                        "resolution": {
                            "local_state": "exact_ready",
                            "pull_performed": False,
                        },
                        "result_ref": "sha256:" + "d" * 64,
                        "response_refs": [],
                        "artifact_refs": [],
                        "effects": [],
                        "output": {
                            "mode": "detailed",
                            "detail": "full",
                            "source": "rote_human_presentation",
                            "format": "text",
                            "primary": "hello result",
                            "manifest": {
                                "response_refs": [],
                                "artifact_refs": [],
                                "effects": [],
                            },
                            "truncated": False,
                            "full_output_ref": None,
                        },
                    }
                ),
            ),
        ]
        session = self.runtime.initial_session(
            run_id="hello-fast-path",
            task_key="hello-fast-path",
            request_original="run hello",
        )

        decision = advance_until_yield(self.runtime, session, root=ROOT)
        self.assertEqual("use_decide", decision.projection["state"]["id"])
        ready = self.runtime.advance_session(
            decision.session,
            ControllerEvent(
                id=EventId("local_play_ready"),
                payload={"request": {"parameters": {}}},
                guards={},
            ),
        ).session
        yielded = advance_until_yield(self.runtime, ready, root=ROOT)

        self.assertEqual("receipt", yielded.projection["state"]["id"])
        self.assertEqual("terminal", yielded.projection["state"]["boundary"])
        self.assertEqual(
            [
                "classify_play_invocation",
                "probe_rote_for_onboarding",
                "inspect_onboarding_identity",
                "inspect_registry_play",
                "prepare_play_run_handoff",
                "run_registry_play",
                "verify_play_output",
                "build_receipt",
            ],
            [item.action for item in decision.trace] + [item.action for item in yielded.trace],
        )
        self.assertNotIn("qualify_request", str(yielded.projection))
        self.assertNotIn("search_authorized_plays", str(yielded.projection))
        self.assertEqual("hello result", yielded.presentations[-1])

    @patch("play.runtime_actions.subprocess.run")
    def test_activation_only_reaches_first_use_affordances_without_model(self, run) -> None:
        orientation = (
            "# Hello, friend.\n\n"
            "**Start small. See what happens. Stay in control.**\n\n"
            "Run Hello uses public data only and declares no writes."
        )
        run.side_effect = [
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "invocation_kind": "greeting",
                        "play_uri": None,
                        "classify_ns": 1,
                    }
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "rote_status": "installed",
                        "rote_command": "/usr/local/bin/rote",
                        "rote_off_path": False,
                        "probe_ns": 1,
                    }
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "identity_status": "authenticated",
                        "email": "friend@example.com",
                        "email_handle": "friend",
                        "identity_ref": "sha256:" + "a" * 64,
                        "whoami_ns": 1,
                    }
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "experience_status": "first_use",
                        "experience_ref": "sha256:" + "b" * 64,
                        "orientation_version": 3,
                        "experience_ns": 1,
                    }
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "orientation_status": "presented",
                        "orientation_version": 3,
                        "orientation_markdown": orientation,
                        "orientation_ref": "sha256:" + "c" * 64,
                        "starter_reference": "https://play.modiqo.ai/modiqo/hello@0.1.0",
                        "orientation_ns": 1,
                        "presentation": {"markdown": orientation},
                        "presentation_markdown": orientation,
                    }
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "orientation_status": "recorded",
                        "orientation_version": 3,
                        "experience_ref": "sha256:" + "b" * 64,
                        "marker_ns": 1,
                    }
                ),
            ),
        ]
        session = self.runtime.initial_session(
            run_id="activation-onboarding",
            task_key="activation-onboarding",
            request_original='User activated the skill "play". Follow the loaded skill instructions.',
        )

        yielded = advance_until_yield(self.runtime, session, root=ROOT)

        self.assertEqual("onboarding_first_offer", yielded.projection["state"]["id"])
        self.assertEqual("human", yielded.projection["state"]["boundary"])
        self.assertEqual("choose_first_use_path", yielded.projection["instruction"]["id"])
        self.assertEqual("Run Hello", yielded.projection["instruction"]["choices"][0]["label"])
        self.assertTrue(yielded.projection["instruction"]["choices"][0]["recommended"])
        self.assertEqual((orientation,), yielded.presentations)
        self.assertNotIn("qualify_request", str(yielded.projection))

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
        self.assertEqual("human", yielded.projection["state"]["boundary"])
        self.assertEqual("present_search_results", yielded.trace[0].action)
        self.assertEqual("search_presented", yielded.trace[0].event)
        self.assertEqual(1, len(yielded.presentations))
        self.assertIn("Search: `release notes`", yielded.presentations[0])

    def test_digest_and_search_selections_bind_the_direct_run_contract(self) -> None:
        from play.runtime_context import apply_event, initial_context

        for mutation in ("enter_awareness_use", "enter_search_use"):
            with self.subTest(mutation=mutation):
                context = initial_context(
                    run_id="run-bind",
                    task_key="task-bind",
                    machine_version="test",
                    request_original="what's new",
                )
                updated = apply_event(
                    context,
                    event_id="selection",
                    payload={
                        "match.reference": "acme/ship-and-tell@0.1.0",
                        "request.parameters": {"channel": "#ship"},
                    },
                    state="use_inspect",
                    transition_seq=1,
                    mutation=mutation,
                )
                self.assertEqual("use", updated["mode"])
                self.assertIsNotNone(updated["request"]["requested_outcome"])
                self.assertIn(
                    "acme/ship-and-tell@0.1.0", updated["request"]["requested_outcome"]
                )
                self.assertEqual({"channel": "#ship"}, updated["request"]["parameters"])

    def test_session_applies_settled_judgment_mutation_before_save_judge(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1",
            task_key="task-1",
            request_original="$play settle cap_abcdefghijklmnop deployed staging and posted the summary",
        )

        advanced = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("settled_task_invocation"),
                payload={
                    "standby": {
                        "armed": True,
                        "task_class": "build-ship-chore",
                        "hook_ref": "cap_abcdefghijklmnop",
                        "settle_summary": "deployed staging and posted the summary",
                    },
                    "capture": {
                        "decision": "capture",
                        "reason": "repeatable deployment",
                        "task_class": "build-ship-chore",
                        "reference": "cap_abcdefghijklmnop",
                        "workspace": "play-capture-abcdefghijklmnop",
                        "status": "verified",
                        "trajectory_ref": "sha256:trajectory",
                    },
                    "execution": {"workspace": "play-capture-abcdefghijklmnop"},
                    "evidence_refs": ["sha256:trajectory"],
                    "request": {
                        "intent": "deployed staging and posted the summary",
                        "requested_outcome": "deployed staging and posted the summary",
                    },
                    "preferences": {"policies": []},
                    "onboarding": {"classify_ns": 1},
                },
                guards={},
            ),
        )

        self.assertEqual("save_judge", advanced.session.cursor.state)
        self.assertEqual("settle", advanced.session.context["mode"])
        self.assertTrue(advanced.session.context["standby"]["armed"])
        self.assertEqual(
            "build-ship-chore", advanced.session.context["standby"]["task_class"]
        )

    def test_session_maps_onboarding_starter_into_use_reference(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-1", task_key="task-1", request_original="$play"
        )
        context = dict(session.context)
        context["state"] = "onboarding_first_offer"
        context["onboarding"] = dict(context["onboarding"])
        context["onboarding"]["orientation_status"] = "recorded"
        starter_uri = "https://play.modiqo.ai/modiqo/hello@0.1.0"
        context["onboarding"]["starter_reference"] = starter_uri
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
                    "onboarding": {"starter_reference": starter_uri},
                },
                guards={},
            ),
        )

        self.assertEqual("use_inspect", advanced.session.cursor.state)
        self.assertEqual(starter_uri, advanced.session.context["match"]["reference"])
        self.assertIn(starter_uri, advanced.session.context["request"]["requested_outcome"])
        self.assertEqual("selected", advanced.session.context["onboarding"]["starter_status"])

    def test_team_creation_reaches_specialist_then_reuses_invite_prompt(self) -> None:
        session = self.runtime.initial_session(
            run_id="team-onboarding", task_key="team-onboarding", request_original="$play"
        )
        context = dict(session.context)
        context["state"] = "onboarding_first_offer"
        context["onboarding"] = dict(context["onboarding"])
        context["onboarding"]["orientation_status"] = "recorded"
        projected = session.__class__(
            schema=session.schema,
            cursor=replace(session.cursor, state=StateId("onboarding_first_offer")),
            context=context,
            preflight_ready=True,
        )

        selected = self.runtime.advance_session(
            projected,
            ControllerEvent(
                id=EventId("onboarding_team_selected"),
                payload={"prompt_version": "1", "selected_at": "2026-08-08T00:00:00Z"},
                guards={},
            ),
        ).session
        self.assertEqual("onboarding_team_handle", selected.cursor.state)

        described = self.runtime.advance_session(
            selected,
            ControllerEvent(
                id=EventId("team_handle_described"),
                payload={
                    "prompt_version": "1",
                    "selected_at": "2026-08-08T00:00:01Z",
                    "team": {"slug": "ada-labs"},
                },
                guards={},
            ),
        ).session
        self.assertEqual("onboarding_team_create", described.cursor.state)
        instruction = self.runtime.project(described.cursor).instruction
        self.assertIsNotNone(instruction)
        assert instruction is not None
        self.assertEqual("rote-org", instruction["specialist"])

        created = self.runtime.advance_session(
            described,
            ControllerEvent(
                id=EventId("team_space_ready"),
                payload={
                    "team": {
                        "slug": "ada-labs",
                        "name": "Ada Labs",
                        "status": "ready",
                        "members": [],
                        "evidence_refs": ["sha256:" + "a" * 64],
                    }
                },
                guards={},
            ),
        ).session

        yielded = advance_until_yield(self.runtime, created, root=ROOT)
        self.assertEqual("team_invite_offer", yielded.projection["state"]["id"])
        self.assertEqual("choose_team_invite", yielded.projection["instruction"]["id"])
        self.assertIn("Team space ready: Ada Labs", yielded.presentations[0])

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

    def test_session_binds_uri_then_identity_gates_before_inspection(self) -> None:
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
                    "request": {"parameters": {}},
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

        self.assertEqual("onboarding_identity", advanced.session.cursor.state)
        identified = self.runtime.advance_session(
            advanced.session,
            ControllerEvent(
                id=EventId("onboarding_identity_ready"),
                payload={
                    "onboarding": {
                        "identity_status": "authenticated",
                        "email": "friend@example.com",
                        "email_handle": "friend",
                        "identity_ref": "sha256:" + "a" * 64,
                        "whoami_ns": 1,
                    }
                },
                guards={},
            ),
        )

        self.assertEqual("use_inspect", identified.session.cursor.state)
        self.assertEqual(uri, identified.session.context["match"]["reference"])

    def test_logged_out_onboarding_selects_provider_and_resumes_identity(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-login", task_key="task-login", request_original="$play"
        )
        context = dict(session.context)
        context["state"] = "onboarding_identity"
        context["onboarding"] = dict(context["onboarding"])
        context["onboarding"].update(
            {
                "intent": "greeting",
                "rote_status": "installed",
                "rote_command": "/tmp/rote",
            }
        )
        session = replace(
            session,
            cursor=replace(session.cursor, state=StateId("onboarding_identity")),
            context=context,
        )

        offered = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("onboarding_identity_setup_required"),
                payload={
                    "onboarding": {
                        "identity_status": "setup_required",
                        "email": None,
                        "email_handle": None,
                        "identity_ref": None,
                        "whoami_ns": 1,
                    }
                },
                guards={},
            ),
        )
        self.assertEqual("onboarding_login_offer", offered.session.cursor.state)
        self.assertEqual(
            ["google", "github", "defer"],
            [
                choice["id"]
                for choice in offered.projection.as_dict()["instruction"]["choices"]
            ],
        )

        selected = self.runtime.advance_session(
            offered.session,
            ControllerEvent(
                id=EventId("onboarding_github_login_selected"),
                payload={
                    "prompt_version": "choose_login_provider",
                    "selected_at": "2026-08-17T00:00:00Z",
                },
                guards={},
            ),
        )
        self.assertEqual("onboarding_login", selected.session.cursor.state)
        self.assertEqual("github", selected.session.context["onboarding"]["login_provider"])
        self.assertEqual("in_progress", selected.session.context["onboarding"]["login_status"])
        instruction = selected.projection.as_dict()["instruction"]
        self.assertEqual("rote-setup", instruction["specialist"])

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

    def test_first_hello_result_must_be_confirmed_and_can_be_replayed(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-first-result",
            task_key="task-first-result",
            request_original="Run Hello",
        )
        context = dict(session.context)
        context["state"] = "use_receipt"
        context["match"] = dict(context["match"])
        context["match"]["reference"] = "modiqo/hello@0.1.0"
        context["evidence"] = dict(context["evidence"])
        context["evidence"]["verification"] = "verify:first-hello"
        context["onboarding"] = dict(context["onboarding"])
        context["onboarding"]["starter_status"] = "selected"
        context["output"] = dict(context["output"])
        context["output"].update(
            {
                "source": "rote_human_presentation",
                "format": "text",
                "primary": "hello from rote proc",
            }
        )
        projected = replace(
            session,
            cursor=replace(session.cursor, state=StateId("use_receipt")),
            context=context,
            preflight_ready=True,
        )

        first = advance_until_yield(self.runtime, projected, root=ROOT)

        self.assertEqual("onboarding_result_offer", first.projection["state"]["id"])
        self.assertEqual("human", first.projection["state"]["boundary"])
        self.assertEqual("confirm_onboarding_result", first.projection["instruction"]["id"])
        self.assertEqual(("hello from rote proc",), first.presentations)

        replay_selected = self.runtime.advance_session(
            first.session,
            ControllerEvent(
                id=EventId("onboarding_result_replay_requested"),
                payload={
                    "prompt_version": "confirm_onboarding_result",
                    "selected_at": "2026-08-18T00:00:00Z",
                },
                guards={},
            ),
        ).session
        replayed = advance_until_yield(self.runtime, replay_selected, root=ROOT)

        self.assertEqual("onboarding_result_offer", replayed.projection["state"]["id"])
        self.assertEqual(("hello from rote proc",), replayed.presentations)
        self.assertEqual("replay_onboarding_result", replayed.trace[0].action)

        confirmed = self.runtime.advance_session(
            replayed.session,
            ControllerEvent(
                id=EventId("onboarding_result_confirmed"),
                payload={
                    "prompt_version": "confirm_onboarding_result",
                    "selected_at": "2026-08-18T00:00:01Z",
                },
                guards={},
            ),
        )
        self.assertEqual("onboarding_activation_present", confirmed.session.cursor.state)

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
    def test_structured_action_blocked_surfaces_its_reason_at_terminal(
        self, run
    ) -> None:
        run.return_value = SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                {
                    "schema": "play.run-result/v1",
                    "ok": False,
                    "event": "action_blocked",
                    "reason": "Crucible authentication output was not recognized",
                    "recoverable": True,
                    "owner": "play",
                    "evidence_refs": ["sha256:blocked"],
                }
            ),
        )
        session = self.runtime.initial_session(
            run_id="session-structured-blocker",
            task_key="task-structured-blocker",
            request_original="Run Crucible assessment",
        )
        context = dict(session.context)
        context["state"] = "use_run"
        context["request"] = {
            **context["request"],
            "requested_outcome": "Assess the landing page",
            "parameters": {"source": "https://www.modiqo.ai"},
        }
        context["match"] = {
            **context["match"],
            "reference": "crucible-heavybit/landing-page-assessment",
        }
        context["inspection"] = {
            **context["inspection"],
            "exact_reference": "crucible-heavybit/landing-page-assessment@0.2.0",
            "disclosure_sha256": "a" * 64,
            "local_change": "none",
        }
        context["authentication"] = {
            **context["authentication"],
            "original_packet": {"schema": "play.run-handoff/v1"},
            "original_packet_sha256": "b" * 64,
        }
        bound = replace(
            session,
            cursor=replace(session.cursor, state=StateId("use_run")),
            context=context,
        )

        yielded = advance_until_yield(self.runtime, bound, root=ROOT)

        self.assertEqual("blocked", yielded.projection["state"]["id"])
        self.assertEqual(
            ("Crucible authentication output was not recognized",),
            yielded.presentations,
        )
        self.assertEqual("action_blocked", yielded.trace[0].event)

    def test_legacy_authentication_failure_blocks_without_a_receipt(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-legacy-auth-failed",
            task_key="task-legacy-auth-failed",
            request_original="Run Crucible assessment",
        )
        context = dict(session.context)
        context["state"] = "use_authentication_execute"
        context["authentication"] = {
            **context["authentication"],
            "source": "rote_authentication_required",
            "status": "approved",
            "owner": "rote-adapter-config",
            "recoverable": True,
            "adapter_id": "crucible",
            "env_var": "ADAPTER_CRUCIBLE_TOKEN",
            "classified_rung": "oauth_dcr",
            "distinguishing_error": "missing: browser authorization required",
            "original_packet": {"schema": "play.run-handoff/v1"},
            "original_packet_sha256": "a" * 64,
            "evidence_refs": ["sha256:auth-required"],
        }
        bound = replace(
            session,
            cursor=replace(session.cursor, state=StateId("use_authentication_execute")),
            context=context,
        )

        advanced = self.runtime.advance_session(
            bound,
            ControllerEvent(
                id=EventId("authentication_failed"),
                payload={
                    "reason": "provider authorization was declined",
                    "evidence_refs": ["sha256:auth-failed"],
                },
                guards={},
            ),
        )

        self.assertEqual("blocked", advanced.session.context["state"])
        self.assertEqual("failed", advanced.session.context["authentication"]["status"])
        self.assertIsNone(advanced.session.context["authentication"]["receipt"])

    @patch("play.runtime_actions.subprocess.run")
    def test_advance_until_yield_inspects_then_resolves_local_play(self, run) -> None:
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
                        "authentication": {
                            "original_packet": {"schema": "play.run-handoff/v1"},
                            "original_packet_sha256": "c" * 64,
                        },
                    }
                ),
            ),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {
                        "event": "play_run_ready",
                        "play": {"version": "0.1.0"},
                        "resolution": {
                            "local_state": "exact_ready",
                            "pull_performed": False,
                        },
                        "result_ref": "sha256:" + "d" * 64,
                        "response_refs": [],
                        "artifact_refs": [],
                        "effects": [],
                        "output": {
                            "mode": "detailed",
                            "detail": "full",
                            "source": "rote_human_presentation",
                            "format": "text",
                            "primary": "hello result",
                            "manifest": {
                                "response_refs": [],
                                "artifact_refs": [],
                                "effects": [],
                            },
                            "truncated": False,
                            "full_output_ref": None,
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

        decision = advance_until_yield(self.runtime, projected, root=ROOT)
        self.assertEqual("use_decide", decision.projection["state"]["id"])
        ready = self.runtime.advance_session(
            decision.session,
            ControllerEvent(
                id=EventId("local_play_ready"),
                payload={"request": {"parameters": {}}},
                guards={},
            ),
        ).session
        yielded = advance_until_yield(self.runtime, ready, root=ROOT)

        self.assertEqual("receipt", yielded.projection["state"]["id"])
        self.assertEqual("terminal", yielded.projection["state"]["boundary"])
        self.assertEqual("inspect_registry_play", decision.trace[0].action)
        self.assertEqual("play_inspected", decision.trace[0].event)
        self.assertEqual("prepare_play_run_handoff", yielded.trace[0].action)
        self.assertEqual("play_run_handoff_ready", yielded.trace[0].event)
        self.assertEqual("run_registry_play", yielded.trace[1].action)
        self.assertEqual("verify_play_output", yielded.trace[2].action)
        self.assertEqual("build_receipt", yielded.trace[3].action)
        self.assertEqual(3600, run.call_args_list[2].kwargs["timeout"])
        self.assertEqual(1, len(decision.presentations))
        self.assertIn("#", decision.presentations[0])
        self.assertEqual(("hello result",), yielded.presentations)

    @patch("play.runtime_actions.subprocess.run")
    def test_full_remote_match_skips_choice_and_reaches_parameter_resolution(
        self, run
    ) -> None:
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

        self.assertEqual("use_decide", yielded.projection["state"]["id"])
        self.assertEqual("model", yielded.projection["state"]["boundary"])
        self.assertEqual(
            ["classify_adequacy", "inspect_registry_play"],
            [item.action for item in yielded.trace],
        )
        self.assertEqual([], yielded.session.context["search"]["results"])
        self.assertEqual([], yielded.session.context["search"]["play_choices"])
        self.assertNotIn("Which matching Play", "\n".join(yielded.presentations))
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
                "public_sample": [
                    {
                        "reference": "modiqo/release-notes",
                        "name": "release-notes",
                        "description": "Draft checked release notes.",
                        "download_count": 12,
                        "parameters": {},
                    }
                ],
                "sample": {
                    "strategy": "random",
                    "limit": 10,
                    "available_count": 1,
                    "sampled_count": 1,
                },
                "ranking": {
                    "label": "Authorized public Plays by lifetime downloads",
                    "complete": True,
                    "eligible_count": 1,
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
        self.assertEqual("human", yielded.projection["state"]["boundary"])
        self.assertEqual(
            ["collect_awareness_digest", "present_awareness_digest"],
            [item.action for item in yielded.trace],
        )
        self.assertEqual(1, len(yielded.presentations))
        self.assertIn("What’s new in Plays", yielded.presentations[0])
        self.assertEqual("random", yielded.session.context["awareness"]["sample_strategy"])
        self.assertEqual(10, yielded.session.context["awareness"]["sample_limit"])
        self.assertEqual(1, yielded.session.context["awareness"]["sampled_count"])
        self.assertEqual(
            "modiqo/release-notes",
            yielded.session.context["awareness"]["play_choices"][0]["reference"],
        )
        dynamic_choices = yielded.projection["instruction"]["choices"]
        self.assertEqual("release-notes", dynamic_choices[0]["label"])

    def test_awareness_sample_selection_binds_the_selected_play(self) -> None:
        from play.runtime_context import apply_event, initial_context

        context = initial_context(
            run_id="sample-select",
            task_key="sample-select",
            machine_version="test",
            request_original="what's new",
        )
        updated = apply_event(
            context,
            event_id="awareness_play_selected",
            payload={
                "match": {"reference": "modiqo/release"},
                "request": {"parameters": {}},
            },
            state="use_inspect",
            transition_seq=1,
            mutation="enter_awareness_use",
        )
        self.assertEqual("modiqo/release", updated["match"]["reference"])
        self.assertEqual("use", updated["mode"])

    def test_session_completes_use_contract_with_typed_parameter_event(self) -> None:
        session = self.runtime.initial_session(
            run_id="session-use", task_key="task-use", request_original="Run Hello"
        )
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("ordinary_play_invocation"),
                payload={"onboarding": {"classify_ns": 1}, "preferences": {"policies": []}},
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
                        "parameters": [],
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
                payload={"request": {"parameters": {}}},
                guards={},
            ),
        ).session
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("play_run_handoff_ready"),
                payload={
                    "authentication": {
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

    @patch(
        "play.runtime_context.resolve_cached_reference",
        return_value="modiqo/retrieve-recent-emails",
    )
    def test_exact_request_repairs_unique_bare_name_before_inspection(
        self, resolve_reference
    ) -> None:
        session = self.runtime.initial_session(
            run_id="session-email",
            task_key="retrieve-recent-emails",
            request_original="c" + "na you retrieve recent emails",
        )
        session = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("ordinary_play_invocation"),
                payload={
                    "onboarding": {"classify_ns": 1},
                    "preferences": {"policies": []},
                },
                guards={},
            ),
        ).session

        advanced = self.runtime.advance_session(
            session,
            ControllerEvent(
                id=EventId("exact_play_request"),
                payload={
                    "request": {
                        "intent": "Run the retrieve-recent-emails Play",
                        "requested_outcome": "Retrieve recent Gmail messages",
                        "parameters": {},
                    },
                    "match": {"reference": "retrieve-recent-emails"},
                    "modality_policy": session.context["modality_policy"],
                },
                guards={},
            ),
        ).session

        resolve_reference.assert_called_once_with("retrieve-recent-emails")
        self.assertEqual("use_inspect", advanced.cursor.state)
        self.assertEqual(
            "modiqo/retrieve-recent-emails",
            advanced.context["match"]["reference"],
        )

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

    def test_event_contract_rejects_unrelated_context_mutation(self) -> None:
        with self.assertRaisesRegex(
            ControllerRuntimeError, "undeclared fields: consent.save"
        ):
            self.runtime.step(
                self.cursor(),
                ControllerEvent(
                    id=EventId("outcome_request"),
                    payload={
                        "request": {"intent": "do work", "requested_outcome": "result"},
                        "modality_policy": {},
                        "capture": {
                            "decision": "normal",
                            "reason": "bounded",
                            "task_class": "unclassified",
                        },
                        "consent": {"save": "public"},
                    },
                    guards={},
                ),
            )

    def test_capture_guard_is_derived_from_bound_trajectory_not_caller(self) -> None:
        session = self.runtime.initial_session(
            run_id="capture-run", task_key="capture-task", request_original="captured"
        )
        context = dict(session.context)
        context["state"] = "crystallize"
        context["capture"] = {
            "decision": "capture",
            "reason": "repeatable",
            "task_class": "ops-maintenance",
            "reference": "cap_abcdefghijklmnop",
            "workspace": "play-capture-abcdefghijklmnop",
            "status": "verified",
            "trajectory_ref": "sha256:trajectory",
        }
        context["execution"] = {**context["execution"], "workspace": "play-capture-abcdefghijklmnop"}
        context["evidence"] = {**context["evidence"], "verification": "sha256:trajectory"}
        bound = replace(
            session,
            cursor=replace(session.cursor, state=StateId("crystallize")),
            context=context,
        )

        advanced = self.runtime.advance_session(
            bound,
            ControllerEvent(
                id=EventId("candidate_ready"),
                payload={
                    "candidate": {
                        "reference": "candidate",
                        "reusable": True,
                        "contract": "contract",
                    }
                },
                guards={GuardId("captured_trajectory_is_verified"): False},
            ),
        )

        self.assertEqual("save_prepare", advanced.session.cursor.state)

    def test_private_org_guard_requires_owner_membership_evidence(self) -> None:
        cursor = replace(self.cursor(), state=StateId("private_org"))
        invalid = self.runtime.step(
            cursor,
            ControllerEvent(
                id=EventId("private_org_ready"),
                payload={
                    "publication": {"private_org": "ada-labs"},
                    "owner": "ada@example.com",
                    "members": [{"email": "other@example.com", "role": "admin"}],
                    "evidence_refs": ["sha256:org"],
                    "organization_receipt": {
                        "schema": "play.rote-org-receipt/v1",
                        "specialist": "rote-org",
                        "operation": "ensure_private_org",
                        "ok": True,
                        "private_org": "ada-labs",
                        "owner": "ada@example.com",
                        "members": [{"email": "other@example.com", "role": "admin"}],
                        "evidence_refs": ["sha256:org"],
                    },
                },
                guards={GuardId("private_org_policy_satisfied"): True},
            ),
        )
        self.assertEqual("blocked", invalid.cursor.state)

        valid = self.runtime.step(
            cursor,
            ControllerEvent(
                id=EventId("private_org_ready"),
                payload={
                    "publication": {"private_org": "ada-labs"},
                    "owner": "ada@example.com",
                    "members": [{"email": "ada@example.com", "role": "owner"}],
                    "evidence_refs": ["sha256:org"],
                    "organization_receipt": {
                        "schema": "play.rote-org-receipt/v1",
                        "specialist": "rote-org",
                        "operation": "ensure_private_org",
                        "ok": True,
                        "private_org": "ada-labs",
                        "owner": "ada@example.com",
                        "members": [{"email": "ada@example.com", "role": "owner"}],
                        "evidence_refs": ["sha256:org"],
                    },
                },
                guards={GuardId("private_org_policy_satisfied"): False},
            ),
        )
        self.assertEqual("private_publish", valid.cursor.state)

    def test_ordered_guard_selects_the_first_satisfied_branch(self) -> None:
        cursor = self.cursor()
        cursor = self.runtime.step(
            cursor,
            ControllerEvent(
                id=EventId("outcome_request"),
                payload={
                    "request": {"intent": "do work", "requested_outcome": "result"},
                    "modality_policy": {},
                    "capture": {
                        "decision": "normal",
                        "reason": "bounded",
                        "task_class": "unclassified",
                    },
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
                    "capture": {
                        "decision": "normal",
                        "reason": "bounded",
                        "task_class": "unclassified",
                    },
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
