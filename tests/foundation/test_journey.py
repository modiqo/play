from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from scripts.lib.play.journey import (
    MAX_SNAPSHOT_NODES,
    PROJECTION_VERSION,
    SCHEMA,
    append_source_event,
    build_graph,
    build_snapshot,
    claim_snapshot,
    doctor,
    journey_directory,
    load_graph,
    load_snapshot,
    materialize_snapshot,
    normalize_dependencies,
    normalize_entries,
    refresh_capture,
    render_snapshot,
    run_worker,
)
from scripts.lib.play.journey_capabilities import adapter_manifest_summary
from scripts.lib.play.private_store import atomic_write_json
from scripts.lib.play.sidekick import start_capture


ROOT = Path(__file__).resolve().parents[2]


def raw_command(
    sequence: int,
    *,
    command_type: str,
    params: dict,
    response_id: int | None,
) -> dict:
    return {
        "sequence": sequence,
        "command_type": command_type,
        "params": json.dumps({"command": command_type, "params": params}),
        "response_ids": json.dumps([response_id] if response_id is not None else []),
        "timestamp": "2026-08-19T00:00:00+00:00",
        "skip_export": False,
    }


def adapter_command(
    sequence: int,
    operation: str,
    response_id: int,
    *,
    envelope: str = "call",
) -> dict:
    wrapper = f"gmail_{envelope}"
    arguments = (
        {"query": "find the Gmail operation"}
        if envelope == "probe"
        else {"tool_name": operation, "arguments": {"query": "secret@example.com"}}
    )
    return raw_command(
        sequence,
        command_type="HttpRequest",
        response_id=response_id,
        params={
            "endpoint": "adapter/gmail",
            "body": {
                "method": "tools/call",
                "params": {
                    "name": wrapper,
                    "arguments": arguments,
                },
            },
        },
    )


class JourneyProjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.journeys = self.base / "journeys"
        self.workspace = self.base / "workspace"
        (self.workspace / ".rote" / "responses").mkdir(parents=True)
        (self.workspace / ".rote" / "workspace.db").write_bytes(b"db")
        self.capture = {
            "reference": "cap_test-journey",
            "intent": "Retrieve rideshare receipts",
            "task_class": "data-fetch-report",
            "workspace": "play-capture-test",
            "workspace_path": str(self.workspace),
            "status": "active",
            "trajectory_ref": None,
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def metadata(
        *,
        ok: bool = True,
        duration: int = 10,
        tokens: int = 20,
        risk_tags: list[str] | None = None,
    ) -> dict:
        value = {"ok": ok, "duration_ms": duration, "tokens": tokens}
        if risk_tags is not None:
            value["process_policy"] = {
                "state": "evaluated",
                "decision": "allowed",
                "risk_tags": risk_tags,
            }
        return value

    def test_normalization_classifies_adapter_work_without_persisting_payloads(self) -> None:
        rows = [
            adapter_command(1, "gmail_probe", 1, envelope="probe"),
            adapter_command(2, "gmail.users.messages.list", 2),
            adapter_command(3, "gmail.users.messages.get", 3),
        ]
        activities = normalize_entries(
            rows,
            response_metadata={
                1: self.metadata(),
                2: self.metadata(),
                3: self.metadata(),
            },
            tool_resolver=lambda _adapter_id, _operation: {"method": "GET"},
        )

        self.assertEqual("capability", activities[0]["kind"])
        self.assertEqual("effect", activities[1]["kind"])
        self.assertEqual("read", activities[1]["effect"])
        self.assertEqual("gmail", activities[1]["provider"])
        self.assertEqual("probe", activities[0]["capability"]["phase"])
        self.assertEqual("gmail_probe", activities[0]["capability"]["wrapper"])
        self.assertEqual(
            {
                "family": "adapter",
                "interface": "api",
                "id": "gmail",
                "phase": "call",
                "mode": "single",
                "wrapper": "gmail_call",
                "tool": "gmail.users.messages.list",
                "operations": ["gmail.users.messages.list"],
                "transport": "adapter",
            },
            {
                key: value
                for key, value in activities[1]["capability"].items()
                if key not in {"schema", "label"}
            },
        )
        serialized = json.dumps(activities)
        self.assertNotIn("secret@example.com", serialized)
        self.assertNotIn("arguments", serialized)

    def test_process_argument_prose_cannot_change_semantic_kind(self) -> None:
        rows = [
            raw_command(
                1,
                command_type="ProcessExec",
                response_id=1,
                params={
                    "invocation": {
                        "program": "sh",
                        "args": [
                            "-c",
                            'curl -fsS https://example.test | rg "Google or GitHub sign-in"',
                        ],
                    }
                },
            ),
            raw_command(
                2,
                command_type="ProcessExec",
                response_id=2,
                params={
                    "invocation": {
                        "program": "rg",
                        "args": ["token permission schema publish", "docs"],
                    }
                },
            ),
        ]

        activities = normalize_entries(
            rows,
            response_metadata={1: self.metadata(), 2: self.metadata()},
        )

        self.assertEqual(("phase", "unknown"), (activities[0]["kind"], activities[0]["role"]))
        self.assertEqual(
            ("phase", "unknown"),
            (activities[1]["kind"], activities[1]["role"]),
        )
        self.assertTrue(all(item["effect_profile"]["source"] == "process_policy_missing" for item in activities))

    def test_process_effects_use_typed_policy_risk_tags(self) -> None:
        rows = [
            raw_command(
                1,
                command_type="ProcessExec",
                response_id=1,
                params={
                    "invocation": {"program": "mystery", "args": []},
                },
            ),
            raw_command(
                2,
                command_type="ProcessExec",
                response_id=2,
                params={
                    "invocation": {"program": "mystery", "args": []},
                },
            ),
            raw_command(
                3,
                command_type="ProcessExec",
                response_id=3,
                params={
                    "invocation": {"program": "mystery", "args": []},
                },
            ),
        ]

        activities = normalize_entries(
            rows,
            response_metadata={
                1: self.metadata(risk_tags=["read_fs"]),
                2: self.metadata(risk_tags=["read_fs", "write_fs"]),
                3: self.metadata(risk_tags=["network"]),
            },
        )

        self.assertEqual(
            [("phase", "inspection"), ("effect", "mixed"), ("phase", "unknown")],
            [(item["kind"], item["role"]) for item in activities],
        )
        self.assertEqual(
            ["read", "mixed", "unknown"],
            [item["effect_profile"]["posture"] for item in activities],
        )
        self.assertEqual("process_policy", activities[0]["effect_profile"]["source"])

    def test_response_metadata_allowlists_process_policy_receipt(self) -> None:
        responses = self.workspace / ".rote" / "responses"
        (responses / "@1.json").write_text(
            json.dumps(
                {
                    "response": {
                        "status": 200,
                        "body": {
                            "policy": {
                                "state": "evaluated",
                                "decision": "warned",
                                "risk_tags": ["write_fs", "read_fs"],
                                "redactions": [{"field": "SECRET", "value": "never-copy"}],
                            },
                            "stdout": "private command output",
                        },
                    }
                }
            )
        )

        from scripts.lib.play.journey import _response_metadata

        metadata = _response_metadata(self.workspace, [1])

        self.assertEqual(
            {
                "state": "evaluated",
                "decision": "warned",
                "risk_tags": ["read_fs", "write_fs"],
            },
            metadata[1]["process_policy"],
        )
        self.assertNotIn("stdout", metadata[1])
        self.assertNotIn("redactions", metadata[1]["process_policy"])

    def test_adapter_effects_use_tool_hints_and_fail_closed_without_them(self) -> None:
        rows = [
            adapter_command(1, "native.read", 1),
            adapter_command(2, "native.write", 2),
            adapter_command(3, "native.opaque", 3),
        ]
        contracts = {
            "native.read": {"method": "MCP", "hints": {"readOnlyHint": True}},
            "native.write": {"method": "MCP", "hints": {"readOnlyHint": False}},
            "native.opaque": {"method": "MCP"},
        }

        activities = normalize_entries(
            rows,
            response_metadata={index: self.metadata() for index in range(1, 4)},
            tool_resolver=lambda _adapter_id, operation: contracts[operation],
        )

        self.assertEqual(
            ["read", "write", "unknown"],
            [item["effect_profile"]["posture"] for item in activities],
        )
        self.assertEqual("unknown", activities[2]["effect"])

    def test_adapter_semantics_use_typed_contracts_not_operation_words(self) -> None:
        operations = [
            "adapter.auth.ensure",
            "tools/list",
            "settings.get",
            "contest.get",
            "issues.create",
            "health.check",
            "report.get",
            "list_send_failures",
            "issues/add-assignees",
            "sign_in",
            "which_skill",
        ]
        activities = normalize_entries(
            [adapter_command(index, operation, index) for index, operation in enumerate(operations, 1)],
            response_metadata={index: self.metadata() for index in range(1, len(operations) + 1)},
            tool_resolver=lambda _adapter_id, operation: {
                "method": "POST" if operation in {"issues.create", "issues/add-assignees", "sign_in"} else "GET"
            },
        )

        self.assertEqual(
            [
                ("authority", None),
                ("effect", "read"),
                ("effect", "read"),
                ("effect", "read"),
                ("effect", "write"),
                ("effect", "read"),
                ("effect", "read"),
                ("effect", "read"),
                ("effect", "write"),
                ("effect", "write"),
                ("effect", "read"),
            ],
            [(item["kind"], item["effect"]) for item in activities],
        )
        self.assertTrue(all(item["effect_profile"]["source"] == "adapter_tool_contract" for item in activities[1:]))

    def test_generic_adapter_calls_use_the_nested_tool_name(self) -> None:
        row = raw_command(
            1,
            command_type="HttpRequest",
            response_id=1,
            params={
                "endpoint": "adapter/github",
                "body": {
                    "method": "tools/call",
                    "params": {
                        "name": "github_call",
                        "arguments": {
                            "tool_name": "pulls/update",
                            "arguments": {"body": "mentions login and token setup"},
                        },
                    },
                },
            },
        )

        activity = normalize_entries(
            [row],
            response_metadata={1: self.metadata()},
            tool_resolver=lambda _adapter_id, _operation: {"method": "PATCH"},
        )[0]

        self.assertEqual("pulls/update", activity["operation"])
        self.assertEqual(("effect", "write"), (activity["kind"], activity["effect"]))
        self.assertEqual("call", activity["capability"]["phase"])
        self.assertEqual(["pulls/update"], activity["capability"]["operations"])

    def test_adapter_batch_call_preserves_each_concrete_operation(self) -> None:
        row = raw_command(
            1,
            command_type="HttpRequest",
            response_id=1,
            params={
                "endpoint": "/adapter/github-api",
                "body": {
                    "method": "tools/call",
                    "params": {
                        "name": "github_api_batch_call",
                        "arguments": {
                            "calls": [
                                {"tool_name": "repos/get", "arguments": {}},
                                {"tool_name": "pulls/list", "arguments": {}},
                            ]
                        },
                    },
                },
            },
        )

        capability = normalize_entries(
            [row], response_metadata={1: self.metadata()}
        )[0]["capability"]

        self.assertEqual(("adapter", "github-api"), (capability["family"], capability["id"]))
        self.assertEqual(("call", "batch"), (capability["phase"], capability["mode"]))
        self.assertEqual(["repos/get", "pulls/list"], capability["operations"])

    def test_generic_http_provider_label_is_not_an_adapter_contract(self) -> None:
        row = raw_command(
            1,
            command_type="HttpRequest",
            response_id=1,
            params={
                "endpoint": "https://api.example.test",
                "body": {"method": "tools/call", "params": {"name": "github_call"}},
            },
        )

        capability = normalize_entries(
            [row], response_metadata={1: self.metadata()}
        )[0]["capability"]

        self.assertEqual("rote", capability["family"])

    def test_browser_inventory_and_reads_have_distinct_semantics(self) -> None:
        rows = [
            raw_command(
                index,
                command_type="HttpRequest",
                response_id=index,
                params={
                    "endpoint": "stdio:/browser",
                    "body": {"method": "tools/call", "params": {"name": operation}},
                },
            )
            for index, operation in enumerate(
                ("initialize", "browser_tabs", "browser_snapshot", "browser_navigate", "browser_click"), 1
            )
        ]
        activities = normalize_entries(
            rows,
            response_metadata={index: self.metadata() for index in range(1, 6)},
        )

        self.assertEqual("capability", activities[0]["kind"])
        self.assertEqual("read", activities[1]["effect"])
        self.assertEqual("read", activities[2]["effect"])
        self.assertEqual("read", activities[3]["effect"])
        self.assertEqual("unknown", activities[4]["effect"])
        self.assertEqual(
            ["lease", "lease", "ledger", "navigate", "action"],
            [item["capability"]["primitive"] for item in activities],
        )
        self.assertTrue(all(item["capability"]["family"] == "browser" for item in activities))

    def test_browser_query_read_becomes_an_evidence_lens(self) -> None:
        rows = [
            raw_command(
                1,
                command_type="HttpRequest",
                response_id=1,
                params={
                    "endpoint": "stdio:/playwright-nosandbox",
                    "body": {"method": "tools/call", "params": {"name": "browser_snapshot"}},
                },
            ),
            raw_command(
                2,
                command_type="QueryRead",
                response_id=None,
                params={"source_response": 1, "query": ".content[0].text"},
            ),
        ]

        activities = normalize_entries(rows, response_metadata={1: self.metadata()})

        self.assertEqual("browser", activities[1]["capability"]["family"])
        self.assertEqual("lens", activities[1]["capability"]["primitive"])

    def test_process_capability_exposes_wrapped_cli_and_execution_mode(self) -> None:
        rows = [
            raw_command(
                1,
                command_type="ProcessExec",
                response_id=1,
                params={
                    "invocation": {
                        "kind": "direct_argv",
                        "program": "npx",
                        "args": ["wrangler", "pages", "deploy", "site"],
                    }
                },
            ),
            raw_command(
                2,
                command_type="ProcessBackgroundStart",
                response_id=2,
                params={
                    "invocation": {
                        "kind": "direct_argv",
                        "program": "python3",
                        "args": ["-m", "http.server"],
                    }
                },
            ),
        ]

        activities = normalize_entries(
            rows,
            response_metadata={1: self.metadata(), 2: self.metadata()},
        )

        self.assertEqual(
            ("proc", "wrangler", "argv"),
            tuple(activities[0]["capability"][key] for key in ("family", "id", "mode")),
        )
        self.assertEqual("background", activities[1]["capability"]["mode"])

    def test_adapter_capability_carries_safe_manifest_contract(self) -> None:
        manifest = {
            "schema": 2,
            "name": "GitHub",
            "spec_type": "openapi3",
            "transport": "http",
            "auth_type": "bearer",
            "operation_scope": "read-write",
            "fingerprint": "mcp_safe",
            "status": "ready",
        }

        activity = normalize_entries(
            [adapter_command(1, "issues.create", 1)],
            response_metadata={1: self.metadata()},
            manifest_resolver=lambda _adapter_id: manifest,
        )[0]

        self.assertEqual("GitHub", activity["capability"]["label"])
        self.assertEqual(manifest, activity["capability"]["manifest"])

    def test_adapter_manifest_summary_allowlists_non_secret_contract_fields(self) -> None:
        adapter = self.base / "rote-home" / "adapters" / "github"
        adapter.mkdir(parents=True)
        (adapter / "manifest.json").write_text(
            json.dumps(
                {
                    "schema": 2,
                    "id": "github",
                    "name": "GitHub",
                    "spec_type": "openapi3",
                    "spec_version": "3.0.3",
                    "fingerprint": "mcp_public_contract",
                    "auth": {"type": "bearer", "token_env": "GITHUB_TOKEN"},
                    "operation_scope": "read-write",
                    "status": "ready",
                    "base_url": "https://api.github.com",
                }
            )
        )
        adapter_manifest_summary.cache_clear()
        with patch.dict(os.environ, {"ROTE_HOME": str(self.base / "rote-home")}):
            summary = adapter_manifest_summary("github")
        adapter_manifest_summary.cache_clear()

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual("http", summary["transport"])
        self.assertEqual("bearer", summary["auth_type"])
        self.assertNotIn("token_env", summary)
        self.assertNotIn("base_url", summary)

    def test_inline_interpreter_source_is_not_semantic_metadata(self) -> None:
        rows = [
            raw_command(
                1,
                command_type="ProcessExec",
                response_id=1,
                params={
                    "invocation": {
                        "program": "python3",
                        "args": ["-c", "print('oauth token schema publish verify')"],
                    }
                },
            ),
            raw_command(
                2,
                command_type="ProcessExec",
                response_id=2,
                params={"invocation": {"program": "python3", "args": ["-m", "pytest"]}},
            ),
        ]
        activities = normalize_entries(
            rows,
            response_metadata={1: self.metadata(), 2: self.metadata()},
        )

        self.assertEqual(("phase", "unknown"), (activities[0]["kind"], activities[0]["role"]))
        self.assertEqual(
            ("phase", "unknown"),
            (activities[1]["kind"], activities[1]["role"]),
        )

    def test_query_reads_attach_to_the_response_they_actually_read(self) -> None:
        rows = [
            adapter_command(1, "gmail.users.messages.get", 1),
            adapter_command(2, "issues.create", 2),
            raw_command(
                3,
                command_type="QueryRead",
                response_id=None,
                params={
                    "source_response": 1,
                    "query": ".messages",
                    "source_response_tokens": 100,
                    "result_tokens": 20,
                },
            ),
        ]
        activities = normalize_entries(
            rows,
            response_metadata={1: self.metadata(), 2: self.metadata()},
            tool_resolver=lambda _adapter_id, operation: {
                "method": "POST" if operation == "issues.create" else "GET"
            },
        )
        graph = build_graph(
            self.capture,
            activities=activities,
            dependencies=[],
            stats={"commands": 3, "responses": 2},
        )

        read_node = next(node for node in graph["nodes"] if node.get("effect") == "read")
        write_node = next(node for node in graph["nodes"] if node.get("effect") == "write")
        self.assertEqual([1, 3], read_node["evidence"]["rote_commands"])
        self.assertEqual([2], write_node["evidence"]["rote_commands"])

    def test_repeated_calls_collapse_and_failed_retry_becomes_recovery(self) -> None:
        rows = [
            adapter_command(1, "gmail.users.messages.list", 1),
            adapter_command(2, "gmail.users.messages.get", 2),
            adapter_command(3, "gmail.users.messages.get", 3),
            adapter_command(4, "gmail.users.messages.get", 4),
        ]
        metadata = {
            1: self.metadata(),
            2: self.metadata(),
            3: self.metadata(ok=False),
            4: self.metadata(),
        }
        snapshot = build_snapshot(
            self.capture,
            activities=normalize_entries(rows, response_metadata=metadata),
            dependencies=[],
            stats={"commands": 4, "responses": 4},
        )

        reads = [node for node in snapshot["nodes"] if node.get("effect") == "read"]
        self.assertEqual(2, reads[0]["activity_count"])
        blocker = next(node for node in snapshot["nodes"] if node["kind"] == "blocker")
        recovery = next(node for node in snapshot["nodes"] if node["kind"] == "recovery")
        self.assertEqual(blocker["id"], recovery["recovered_node"])
        self.assertIn(
            {
                "source": blocker["id"],
                "target": recovery["id"],
                "kind": "recovers",
            },
            snapshot["edges"],
        )

    def test_dependency_edges_resolve_through_opaque_evidence_refs(self) -> None:
        rows = [
            adapter_command(1, "gmail.users.messages.list", 11),
            raw_command(
                2,
                command_type="ProcessExec",
                response_id=12,
                params={
                    "invocation": {
                        "program": "deno",
                        "args": ["eval", "sensitive transformation source"],
                    }
                },
            ),
        ]
        snapshot = build_snapshot(
            self.capture,
            activities=normalize_entries(
                rows,
                response_metadata={11: self.metadata(), 12: self.metadata()},
            ),
            dependencies=[
                {"source_response": 11, "target_sequence": 2, "kind": "query-read-result"}
            ],
            stats={"commands": 2, "responses": 2},
        )

        self.assertTrue(any(edge["kind"] == "derived_from" for edge in snapshot["edges"]))
        self.assertNotIn("sensitive transformation source", json.dumps(snapshot))

    def test_causal_traversal_edges_use_the_closed_semantic_vocabulary(self) -> None:
        kinds = (
            "decision",
            "capability",
            "authority",
            "effect",
            "blocker",
            "recovery",
            "evidence",
            "milestone",
            "play_candidate",
        )
        activities = [
            {
                "sequence": sequence,
                "command_type": "Synthetic",
                "response_refs": [f"@{sequence}"],
                "operation": f"{kind}-{sequence}",
                "provider": "posthog" if kind in {"capability", "authority", "effect"} else None,
                "kind": kind,
                "role": "verification" if kind == "evidence" else None,
                "effect": "read" if kind == "effect" else None,
                "status": "succeeded",
                "duration_ms": 1,
                "tokens": 0,
                "tokens_saved": 0,
                "signature": f"sig-{sequence}",
                "timestamp": None,
            }
            for sequence, kind in enumerate(kinds, 1)
        ]
        graph = build_graph(
            self.capture,
            activities=activities,
            dependencies=[],
            stats={"commands": len(activities), "responses": len(activities)},
        )
        nodes = {node["kind"]: node["id"] for node in graph["nodes"]}
        edges = {
            (edge["source"], edge["target"], edge["kind"])
            for edge in graph["edges"]
        }

        self.assertIn((nodes["decision"], nodes["capability"], "selects"), edges)
        self.assertIn((nodes["authority"], nodes["effect"], "authorizes"), edges)
        self.assertIn((nodes["capability"], nodes["effect"], "executes"), edges)
        self.assertIn((nodes["effect"], nodes["evidence"], "produces"), edges)
        self.assertIn((nodes["blocker"], nodes["recovery"], "recovers"), edges)
        self.assertIn((nodes["evidence"], nodes["milestone"], "verifies"), edges)
        self.assertIn(
            (nodes["evidence"], nodes["play_candidate"], "crystallizes_into"),
            edges,
        )

    def test_dependency_normalization_has_no_canonical_edge_cap(self) -> None:
        dependencies = normalize_dependencies(
            [
                {
                    "source_response": sequence,
                    "command_sequence": sequence + 1,
                    "dependency_type": "query-read-result",
                }
                for sequence in range(1, 5001)
            ]
        )
        self.assertEqual(5000, len(dependencies))

    def test_snapshot_validates_against_the_strict_contract(self) -> None:
        snapshot = build_snapshot(
            self.capture,
            activities=normalize_entries(
                [adapter_command(1, "gmail.users.messages.list", 1)],
                response_metadata={1: self.metadata()},
            ),
            dependencies=[],
            stats={"commands": 1, "responses": 1},
        )
        schema = json.loads(
            (ROOT / "references/explore/journey-viewport.schema.json").read_text()
        )

        Draft202012Validator(schema).validate(snapshot)
        self.assertEqual(SCHEMA, snapshot["schema"])

    def test_viewport_caps_evidence_references_without_pruning_the_graph(self) -> None:
        rows = [
            adapter_command(sequence, "gmail.users.messages.get", sequence)
            for sequence in range(1, 201)
        ]
        graph = build_graph(
            self.capture,
            activities=normalize_entries(
                rows,
                response_metadata={sequence: self.metadata() for sequence in range(1, 201)},
            ),
            dependencies=[],
            stats={"commands": 200, "responses": 200},
        )
        full_node = next(node for node in graph["nodes"] if node.get("effect") == "read")
        snapshot = materialize_snapshot(graph)
        view_node = next(node for node in snapshot["nodes"] if node.get("effect") == "read")

        self.assertEqual(200, len(full_node["evidence"]["rote_commands"]))
        self.assertEqual(128, len(view_node["evidence"]["rote_commands"]))
        self.assertEqual(144, snapshot["presentation"]["evidence_refs_omitted"])
        schema = json.loads(
            (ROOT / "references/explore/journey-viewport.schema.json").read_text()
        )
        Draft202012Validator(schema).validate(snapshot)

    def test_large_graph_is_fully_persisted_while_snapshot_is_a_bounded_view(self) -> None:
        activities = []
        for sequence in range(1, MAX_SNAPSHOT_NODES + 120):
            activities.append(
                {
                    "sequence": sequence,
                    "command_type": "ProcessExec",
                    "response_refs": [f"@{sequence}"],
                    "operation": f"tool-{sequence}",
                    "provider": None,
                    "kind": "phase",
                    "role": "local",
                    "effect": None,
                    "status": "succeeded",
                    "duration_ms": 1,
                    "tokens": 0,
                    "tokens_saved": 0,
                    "signature": f"sig-{sequence}",
                    "timestamp": None,
                }
            )
        dependencies = [
            {
                "source_response": sequence,
                "target_sequence": sequence + 1,
                "kind": "query-read-result",
            }
            for sequence in range(1, len(activities))
        ]
        graph = build_graph(
            self.capture,
            activities=activities,
            dependencies=dependencies,
            stats={"commands": len(activities), "responses": len(activities)},
        )
        snapshot = materialize_snapshot(graph)
        graph_schema = json.loads(
            (ROOT / "references/explore/journey-graph.schema.json").read_text()
        )
        Draft202012Validator(graph_schema).validate(graph)

        self.assertGreater(len(graph["nodes"]), MAX_SNAPSHOT_NODES)
        self.assertGreater(len(graph["edges"]), 384)
        self.assertEqual(
            len(graph["nodes"]),
            len(graph["presentation"]["changed_node_ids"]),
        )
        self.assertLessEqual(len(snapshot["nodes"]), MAX_SNAPSHOT_NODES)
        self.assertLessEqual(len(snapshot["presentation"]["changed_node_ids"]), 64)
        self.assertFalse(snapshot["presentation"]["complete"])
        self.assertEqual(len(graph["nodes"]), snapshot["presentation"]["total_nodes"])
        self.assertEqual(len(graph["edges"]), snapshot["presentation"]["total_edges"])
        self.assertGreater(snapshot["presentation"]["evidence_refs_omitted"], 0)
        summary = next(
            node for node in snapshot["nodes"] if node["id"] == "node_compacted_history"
        )
        self.assertGreater(summary["activity_count"], 0)
        self.assertLess(len(json.dumps(snapshot).encode()), 512 * 1024)

        from scripts.lib.play.journey import _persist_graph_state

        _persist_graph_state(
            self.capture["reference"],
            fingerprint="f" * 64,
            command_count=len(activities),
            activities=activities,
            dependencies=dependencies,
            graph=graph,
            root=self.journeys,
        )
        persisted = load_graph(self.capture["reference"], root=self.journeys)
        assert persisted is not None
        self.assertEqual(
            [node["id"] for node in graph["nodes"]],
            [node["id"] for node in persisted["nodes"]],
        )
        self.assertEqual(graph["edges"], persisted["edges"])
        database = journey_directory(
            self.capture["reference"], root=self.journeys
        ) / "journey.sqlite3"
        self.assertEqual(0o600, database.stat().st_mode & 0o777)
        connection = sqlite3.connect(database)
        try:
            self.assertEqual(
                len(activities),
                connection.execute("SELECT COUNT(*) FROM activities").fetchone()[0],
            )
            self.assertEqual(
                len(dependencies),
                connection.execute("SELECT COUNT(*) FROM dependencies").fetchone()[0],
            )
            self.assertEqual(
                len(graph["nodes"]),
                connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            )
            self.assertEqual(
                len(graph["edges"]),
                connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            )
        finally:
            connection.close()

    def test_source_events_are_bounded_private_and_deduplicated_in_projection(self) -> None:
        for _ in range(2):
            self.assertTrue(
                append_source_event(
                    self.capture["reference"],
                    kind="decision",
                    label="Choose Gmail <script>alert(1)</script>",
                    source="play_transition",
                    source_id="run:1:event",
                    root=self.journeys,
                )
            )
        events_path = journey_directory(
            self.capture["reference"], root=self.journeys
        ) / "events.jsonl"
        self.assertEqual(0o600, events_path.stat().st_mode & 0o777)
        lines = events_path.read_text().splitlines()
        self.assertEqual(2, len(lines))
        self.assertNotIn("<script>", lines[0])

        from scripts.lib.play.journey import _read_events

        self.assertEqual(1, len(_read_events(self.capture["reference"], root=self.journeys)))

    def test_grouped_lifecycle_nodes_retain_every_event_reference(self) -> None:
        events = [
            {
                "id": "sha256:first",
                "kind": "decision",
                "label": "Refine the useful outcome",
            },
            {
                "id": "sha256:second",
                "kind": "decision",
                "label": "Refine the useful outcome",
            },
        ]
        graph = build_graph(
            self.capture,
            activities=[],
            dependencies=[],
            stats={"commands": 0, "responses": 0},
            events=events,
        )

        decision = next(node for node in graph["nodes"] if node["kind"] == "decision")
        self.assertEqual(2, decision["activity_count"])
        self.assertEqual(
            ["sha256:first", "sha256:second"],
            decision["evidence"]["play_events"],
        )

    def test_incremental_refresh_uses_json_surfaces_and_skips_unchanged_workspace(self) -> None:
        rows = [adapter_command(1, "gmail_probe", 1)]
        responses = self.workspace / ".rote" / "responses"
        (responses / "@1.json").write_text(
            json.dumps(
                {
                    "response": {"status": 200, "duration_ms": 17, "body": {}},
                    "tokens": {"total_tokens": 23},
                }
            )
        )
        calls: list[tuple[str, ...]] = []

        def rote(_workspace: Path, arguments: list[str]):
            calls.append(tuple(arguments))
            if arguments == ["workspace", "stats", "--json"]:
                return {"commands": 1, "responses": 1, "token_savings": {"tokens_saved": 5}}
            if "log" in arguments:
                return rows
            if "deps" in arguments:
                return []
            raise AssertionError(arguments)

        with patch("scripts.lib.play.journey._run_rote_json", side_effect=rote):
            first = refresh_capture(self.capture, root=self.journeys)
            second = refresh_capture(self.capture, root=self.journeys)

        assert first is not None
        self.assertEqual(3, len(calls))
        self.assertEqual(first, second)
        self.assertEqual(17, first["telemetry"]["duration_ms"])
        self.assertEqual(23, first["telemetry"]["payload_tokens"])

    def test_projection_rule_upgrade_reclassifies_an_unchanged_workspace(self) -> None:
        rows = [adapter_command(1, "gmail_probe", 1)]
        calls: list[tuple[str, ...]] = []

        def rote(_workspace: Path, arguments: list[str]):
            calls.append(tuple(arguments))
            if arguments == ["workspace", "stats", "--json"]:
                return {"commands": 1, "responses": 1}
            if "log" in arguments:
                return rows
            if "deps" in arguments:
                return []
            raise AssertionError(arguments)

        with patch("scripts.lib.play.journey._run_rote_json", side_effect=rote):
            first = refresh_capture(self.capture, root=self.journeys)
            assert first is not None
            database = journey_directory(self.capture["reference"], root=self.journeys) / "journey.sqlite3"
            with sqlite3.connect(database) as connection:
                encoded = connection.execute(
                    "SELECT value FROM meta WHERE key = 'graph_header'"
                ).fetchone()[0]
                header = json.loads(encoded)
                header["projection_version"] = "rules-v1"
                connection.execute(
                    "UPDATE meta SET value = ? WHERE key = 'graph_header'",
                    (json.dumps(header),),
                )
            second = refresh_capture(self.capture, root=self.journeys)

        assert second is not None
        self.assertEqual(PROJECTION_VERSION, second["projection_version"])
        self.assertEqual(6, len(calls))

    def test_idle_fingerprint_is_constant_time_with_respect_to_response_count(self) -> None:
        from scripts.lib.play.journey import _workspace_fingerprint

        with patch.object(Path, "glob", side_effect=AssertionError("must not scan responses")):
            fingerprint = _workspace_fingerprint(self.workspace)
        self.assertEqual(64, len(fingerprint))

    def test_foreground_claim_reads_snapshot_once_and_never_runs_a_subprocess(self) -> None:
        snapshot = build_snapshot(
            self.capture,
            activities=normalize_entries(
                [adapter_command(1, "gmail.users.messages.list", 1)],
                response_metadata={1: self.metadata()},
            ),
            dependencies=[],
            stats={"commands": 1, "responses": 1},
        )
        directory = journey_directory(self.capture["reference"], root=self.journeys)
        atomic_write_json(directory / "snapshot.json", snapshot)

        started = time.perf_counter_ns()
        with patch("subprocess.run") as subprocess_run, patch("subprocess.Popen") as popen:
            claimed = claim_snapshot(
                self.capture, root=self.journeys, force=True, min_interval_seconds=0
            )
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000

        self.assertEqual(snapshot, claimed)
        subprocess_run.assert_not_called()
        popen.assert_not_called()
        self.assertLess(elapsed_ms, 100)
        self.assertIsNone(
            claim_snapshot(self.capture, root=self.journeys, force=True, min_interval_seconds=0)
        )

    def test_worker_failure_is_diagnostic_only(self) -> None:
        standby = self.base / "standby.json"
        atomic_write_json(standby, {"captures": [self.capture], "hooks": []})
        with patch("scripts.lib.play.journey.os.nice"), patch(
            "scripts.lib.play.journey.refresh_capture", side_effect=RuntimeError("schema drift")
        ):
            self.assertEqual(
                0,
                run_worker(
                    self.capture["reference"],
                    standby_path=standby,
                    root=self.journeys,
                    once=True,
                ),
            )
        health = doctor(self.capture["reference"], root=self.journeys)["worker"]
        self.assertEqual("degraded", health["state"])
        self.assertIn("schema drift", health["detail"])

    def test_capture_launches_journey_only_after_the_private_record_exists(self) -> None:
        standby = self.base / "standby-launch.json"
        observed: list[tuple[str, bool]] = []

        def initialize(_name: str) -> Path:
            return self.workspace

        def launch(capture: dict, *, standby_path: Path) -> bool:
            persisted = json.loads(standby_path.read_text())
            observed.append((capture["reference"], bool(persisted["captures"])))
            return True

        with patch.dict(os.environ, {"PLAY_JOURNEY_ROOT": str(self.journeys)}):
            capture = start_capture(
                intent="Explore Gmail",
                task_class="exploration",
                reason="no_match",
                path=standby,
                workspace_initializer=initialize,
                journey_launcher=launch,
            )

        self.assertEqual([(capture["reference"], True)], observed)
        self.assertTrue(
            (journey_directory(capture["reference"], root=self.journeys) / "events.jsonl").is_file()
        )

    def test_semantic_render_uses_human_nodes_not_raw_command_rows(self) -> None:
        snapshot = build_snapshot(
            self.capture,
            activities=normalize_entries(
                [adapter_command(1, "gmail.users.messages.list", 1)],
                response_metadata={1: self.metadata(duration=31, tokens=41)},
            ),
            dependencies=[],
            stats={"commands": 1, "responses": 1},
        )
        text = render_snapshot(snapshot)

        self.assertIn("Retrieve rideshare receipts", text)
        self.assertIn("Retrieve data from Gmail", text)
        self.assertIn("31ms operation time", text)
        self.assertNotIn("gmail.users.messages.list", text)
        self.assertNotIn("@1", text)


if __name__ == "__main__":
    unittest.main()
