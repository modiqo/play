from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.handoff import owner_for_modalities, prepare_handoff, verify_receipt


class HandoffTest(unittest.TestCase):
    def input(self, *, owner: str = "rote-using-adapters", available: list[str] | None = None):
        return {
            "run_id": "play-run-17",
            "requested_outcome": "Find Heavybit founder perks.",
            "owner": owner,
            "modalities": ["call"],
            "available_owners": available or [],
            "constraints": {"read_only": True},
            "inputs": {"query": "Heavybit founder perks discounts"},
            "effect_policy": {
                "read_only": True,
                "approval_gates": [],
                "rote_confirmation": None,
            },
            "evidence_contract": ["response_refs"],
            "idempotency_key": "play-run-17:execute-route:1",
        }

    def receipt(self, prepared: dict) -> dict:
        packet = prepared["packet"]
        return {
            "schema": "play.handoff-receipt/v1",
            "packet_sha256": prepared["packet_sha256"],
            "run_id": packet["run_id"],
            "state": packet["state"],
            "action": packet["action"],
            "owner": packet["owner"],
            "executor": {"kind": "skill", "name": packet["owner"]},
            "event": "outcome_ready",
            "payload": {
                "result_ref": "result:1",
                "response_refs": ["response:1"],
                "artifact_refs": [],
                "modalities_used": ["call"],
                "effects": ["read"],
                "route_provenance": {
                    "kind": "rote_adapter",
                    "adapter_id": "crucible",
                    "substrate": "mcp",
                    "type_evidence_ref": "discovery:mcp-server-card",
                    "adapter_status": "created",
                    "creation_owner": "rote-adapter-create",
                    "auth_status": "completed",
                    "auth_owner": "rote-adapter-config",
                    "orchestration_owner": packet["owner"],
                    "adapter_execute_owner": "rote-using-adapters",
                    "direct_tool_execution": False,
                    "evidence_refs": ["adapter:crucible", "auth:crucible"],
                },
            },
            "evidence_refs": ["response:1"],
        }

    def confirmation_receipt(self, prepared: dict) -> dict:
        packet = prepared["packet"]
        return {
            "schema": "play.handoff-receipt/v1",
            "packet_sha256": prepared["packet_sha256"],
            "run_id": packet["run_id"],
            "state": packet["state"],
            "action": packet["action"],
            "owner": packet["owner"],
            "executor": {"kind": "skill", "name": packet["owner"]},
            "event": "confirmation_required",
            "payload": {
                "effect_confirmation": {
                    "source": "rote_confirmation_required",
                    "status": "required",
                    "tool": "sales_and_commercial",
                    "impact": "Load the pricing and packaging skill.",
                    "confirm_token": "confirm-17",
                    "workspace": "crucible-pricing-strategies",
                    "evidence_refs": ["response:guard-1"],
                }
            },
            "evidence_refs": ["response:guard-1"],
        }

    def test_owner_is_closed_over_modalities(self) -> None:
        self.assertEqual("rote-using-adapters", owner_for_modalities(["call"]))
        self.assertEqual("rote-shell", owner_for_modalities(["shell"]))
        self.assertEqual("rote-browse", owner_for_modalities(["drive"]))
        self.assertEqual("rote-workspace", owner_for_modalities(["call", "shell"]))

    def test_call_blocks_when_adapter_specialist_is_not_exposed(self) -> None:
        result = prepare_handoff(self.input(available=["rote-shell"]))
        self.assertFalse(result["ok"])
        self.assertEqual("specialist_unavailable", result["event"])
        self.assertEqual("rote-using-adapters", result["required_owner"])

    def test_direct_mcp_owner_is_rejected(self) -> None:
        result = prepare_handoff(
            self.input(owner="crucible.search_library", available=["crucible.search_library"])
        )
        self.assertFalse(result["ok"])
        self.assertEqual("specialist_unavailable", result["event"])
        self.assertEqual("rote-using-adapters", result["required_owner"])

    def test_matching_specialist_receipt_is_accepted(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        policy = prepared["packet"]["capability_policy"]
        self.assertEqual("auto", policy["type_selection"])
        self.assertEqual(["openapi", "graphql", "mcp"], policy["substrate_detection"])
        self.assertEqual("rote-adapter-create", policy["create_owner"])
        self.assertEqual("rote-adapter-config", policy["configure_owner"])
        result = verify_receipt({"packet": prepared["packet"], "receipt": self.receipt(prepared)})
        self.assertTrue(result["ok"])
        self.assertEqual("specialist_outcome_ready", result["event"])

    def test_probe_hints_are_not_an_approval_gate(self) -> None:
        payload = self.input(available=["rote-using-adapters"])
        payload["inputs"]["probe_hints"] = {
            "readOnlyHint": False,
            "destructiveHint": True,
        }
        prepared = prepare_handoff(payload)
        self.assertTrue(prepared["ok"])
        self.assertEqual("specialist_handoff_ready", prepared["event"])
        self.assertIn("confirmation_required", prepared["packet"]["expected_events"])

    def test_rote_confirmation_required_receipt_is_accepted(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        result = verify_receipt(
            {"packet": prepared["packet"], "receipt": self.confirmation_receipt(prepared)}
        )
        self.assertTrue(result["ok"])
        self.assertEqual("specialist_confirmation_required", result["event"])
        self.assertEqual("confirm-17", result["effect_confirmation"]["confirm_token"])

    def test_confirmation_cannot_be_inferred_from_probe_metadata(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        receipt = self.confirmation_receipt(prepared)
        receipt["payload"]["effect_confirmation"]["source"] = "probe_hints"
        result = verify_receipt({"packet": prepared["packet"], "receipt": receipt})
        self.assertFalse(result["ok"])
        self.assertIn("rote_confirmation_required", " ".join(result["reasons"]))

    def test_raw_mcp_result_cannot_satisfy_receipt(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        result = verify_receipt(
            {
                "packet": prepared["packet"],
                "receipt": {"results": [{"title": "Founder perks"}]},
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual("specialist_receipt_invalid", result["event"])

    def test_receipt_from_wrong_owner_is_rejected(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        receipt = copy.deepcopy(self.receipt(prepared))
        receipt["executor"]["name"] = "crucible.search_library"
        result = verify_receipt({"packet": prepared["packet"], "receipt": receipt})
        self.assertFalse(result["ok"])
        self.assertIn("executor name", " ".join(result["reasons"]))

    def test_call_receipt_without_adapter_provenance_is_rejected(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        receipt = self.receipt(prepared)
        del receipt["payload"]["route_provenance"]
        result = verify_receipt({"packet": prepared["packet"], "receipt": receipt})
        self.assertFalse(result["ok"])
        self.assertIn("route_provenance", " ".join(result["reasons"]))

    def test_call_receipt_with_direct_mcp_execution_is_rejected(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        receipt = self.receipt(prepared)
        receipt["payload"]["route_provenance"]["direct_tool_execution"] = True
        result = verify_receipt({"packet": prepared["packet"], "receipt": receipt})
        self.assertFalse(result["ok"])
        self.assertIn("direct_tool_execution", " ".join(result["reasons"]))

    def test_call_receipt_requires_detected_adapter_type(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        receipt = self.receipt(prepared)
        receipt["payload"]["route_provenance"]["substrate"] = "rest"
        result = verify_receipt({"packet": prepared["packet"], "receipt": receipt})
        self.assertFalse(result["ok"])
        self.assertIn("openapi, graphql, or mcp", " ".join(result["reasons"]))


if __name__ == "__main__":
    unittest.main()
