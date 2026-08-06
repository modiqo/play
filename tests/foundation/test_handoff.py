from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.handoff import (
    owner_for_modalities,
    prepare_auth_repair_handoff,
    prepare_handoff,
    verify_auth_repair_receipt,
    verify_receipt,
)


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
            "adapter_discovery": {
                "status": "installed_ready",
                "query": "crucible",
                "searched_sources": ["installed"],
                "choices": [
                    {
                        "id": "crucible",
                        "label": "crucible",
                        "description": "Installed Crucible MCP adapter",
                        "source": "installed",
                        "provider": "Heavybit",
                        "category": None,
                        "substrate": "mcp",
                        "auth_shape": "oauth2",
                        "health": "ready",
                        "install_impact": "none",
                        "next_command": "rote adapter info crucible",
                    }
                ],
                "selected_id": "crucible",
                "evidence_refs": ["adapter:crucible"],
            },
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

    def auth_repair_required_receipt(self, prepared: dict) -> dict:
        packet = prepared["packet"]
        return {
            "schema": "play.handoff-receipt/v1",
            "packet_sha256": prepared["packet_sha256"],
            "run_id": packet["run_id"],
            "state": packet["state"],
            "action": packet["action"],
            "owner": packet["owner"],
            "executor": {"kind": "skill", "name": packet["owner"]},
            "event": "auth_repair_required",
            "payload": {
                "auth_repair": {
                    "source": "rote_auth_repair_required",
                    "status": "required",
                    "recoverable": True,
                    "adapter_id": "crucible",
                    "env_var": "CRUCIBLE_TOKEN",
                    "classified_rung": "oauth_subject_rejected",
                    "distinguishing_error": "OAuth subject is no longer accepted",
                    "evidence_refs": ["response:auth-1"],
                }
            },
            "evidence_refs": ["response:auth-1"],
        }

    def auth_repair_input(self, prepared: dict, auth_repair: dict) -> dict:
        return {
            "run_id": prepared["packet"]["run_id"],
            "available_owners": ["rote-adapter-config"],
            "auth_repair": auth_repair,
            "original_packet": prepared["packet"],
            "original_packet_sha256": prepared["packet_sha256"],
            "evidence_contract": ["evidence_refs"],
            "idempotency_key": "play-run-17:auth-repair:1",
        }

    def auth_repair_receipt(self, prepared: dict) -> dict:
        packet = prepared["packet"]
        requested = packet["auth_repair"]
        return {
            "schema": "play.auth-repair-receipt/v1",
            "packet_sha256": prepared["packet_sha256"],
            "run_id": packet["run_id"],
            "state": packet["state"],
            "action": packet["action"],
            "owner": packet["owner"],
            "executor": {"kind": "skill", "name": "rote-adapter-config"},
            "event": "auth_repair_ready",
            "payload": {
                "auth_repair": {
                    "source": "rote_auth_repair_result",
                    "status": "repaired",
                    "adapter_id": requested["adapter_id"],
                    "env_var": requested["env_var"],
                    "classified_rung": requested["classified_rung"],
                    "repair_action": "reauth",
                    "evidence_refs": ["auth:repair-1"],
                }
            },
            "evidence_refs": ["auth:repair-1"],
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

    def test_call_packet_requires_typed_adapter_discovery(self) -> None:
        payload = self.input(available=["rote-using-adapters"])
        del payload["adapter_discovery"]
        with self.assertRaisesRegex(ValueError, "typed adapter_discovery"):
            prepare_handoff(payload)

    def test_zero_catalog_results_can_fall_through_to_spec_discovery(self) -> None:
        payload = self.input(available=["rote-using-adapters"])
        payload["adapter_discovery"] = {
            "status": "catalog_empty",
            "query": "unlisted provider",
            "searched_sources": ["installed", "catalog"],
            "choices": [],
            "selected_id": None,
            "evidence_refs": ["adapter-list:1", "adapter-catalog-search:1"],
        }
        prepared = prepare_handoff(payload)
        self.assertTrue(prepared["ok"])
        self.assertEqual("catalog_empty", prepared["packet"]["adapter_discovery"]["status"])

    def test_selected_catalog_entry_is_bound_into_the_call_packet(self) -> None:
        payload = self.input(available=["rote-using-adapters"])
        choice = payload["adapter_discovery"]["choices"][0]
        choice.update(
            {
                "id": "stripe",
                "label": "Stripe REST API",
                "description": "Catalog OpenAPI adapter for Stripe",
                "source": "catalog",
                "provider": "Stripe",
                "category": "Payments",
                "substrate": "openapi",
                "auth_shape": "static_token",
                "health": "unknown",
                "install_impact": "local-write",
                "next_command": "rote adapter catalog info stripe --json",
            }
        )
        payload["adapter_discovery"].update(
            {
                "status": "selected",
                "query": "stripe",
                "searched_sources": ["installed", "catalog"],
                "selected_id": "stripe",
                "evidence_refs": ["adapter-list:1", "adapter-catalog-search:stripe"],
            }
        )
        prepared = prepare_handoff(payload)

        self.assertTrue(prepared["ok"])
        self.assertEqual("stripe", prepared["packet"]["adapter_discovery"]["selected_id"])

    def test_unselected_catalog_choices_cannot_enter_execution_handoff(self) -> None:
        payload = self.input(available=["rote-using-adapters"])
        payload["adapter_discovery"].update(
            {
                "status": "catalog_choices",
                "searched_sources": ["installed", "catalog"],
                "selected_id": None,
            }
        )
        with self.assertRaisesRegex(ValueError, "not handoff-ready"):
            prepare_handoff(payload)

    def test_catalog_cannot_be_skipped_after_an_installed_miss(self) -> None:
        payload = self.input(available=["rote-using-adapters"])
        payload["adapter_discovery"] = {
            "status": "catalog_empty",
            "query": "unlisted provider",
            "searched_sources": ["installed"],
            "choices": [],
            "selected_id": None,
            "evidence_refs": ["adapter-list:1"],
        }
        with self.assertRaisesRegex(ValueError, "installed then catalog order|catalog_empty"):
            prepare_handoff(payload)

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

    def test_recoverable_auth_failure_enters_typed_repair_contract(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        receipt = self.auth_repair_required_receipt(prepared)
        result = verify_receipt({"packet": prepared["packet"], "receipt": receipt})

        self.assertTrue(result["ok"])
        self.assertEqual("specialist_auth_repair_required", result["event"])
        self.assertEqual("oauth_subject_rejected", result["auth_repair"]["classified_rung"])

    def test_auth_repair_request_rejects_undeclared_credential_material(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        receipt = self.auth_repair_required_receipt(prepared)
        receipt["payload"]["auth_repair"]["token"] = "must-not-enter-play"

        result = verify_receipt({"packet": prepared["packet"], "receipt": receipt})

        self.assertFalse(result["ok"])
        self.assertIn("undeclared fields", " ".join(result["reasons"]))

    def test_auth_repair_request_is_rejected_for_non_call_routes(self) -> None:
        payload = self.input(owner="rote-shell", available=["rote-shell"])
        payload["modalities"] = ["shell"]
        prepared = prepare_handoff(payload)
        receipt = self.auth_repair_required_receipt(prepared)

        result = verify_receipt({"packet": prepared["packet"], "receipt": receipt})

        self.assertFalse(result["ok"])
        self.assertIn("only for a CALL route", " ".join(result["reasons"]))

    def test_auth_repair_handoff_is_closed_to_adapter_config(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        receipt = self.auth_repair_required_receipt(prepared)
        verified = verify_receipt({"packet": prepared["packet"], "receipt": receipt})
        repair_input = self.auth_repair_input(prepared, verified["auth_repair"])

        repair_input["available_owners"] = ["rote-using-adapters"]
        unavailable = prepare_auth_repair_handoff(repair_input)
        self.assertFalse(unavailable["ok"])
        self.assertEqual("auth_repair_specialist_unavailable", unavailable["event"])

        repair_input["available_owners"] = ["rote-adapter-config"]
        repair = prepare_auth_repair_handoff(repair_input)
        self.assertTrue(repair["ok"])
        self.assertEqual("rote-adapter-config", repair["packet"]["owner"])
        self.assertEqual(prepared["packet_sha256"], repair["packet"]["original_packet_sha256"])

    def test_auth_repair_receipt_must_match_requested_shape(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        required = verify_receipt(
            {
                "packet": prepared["packet"],
                "receipt": self.auth_repair_required_receipt(prepared),
            }
        )
        repair = prepare_auth_repair_handoff(
            self.auth_repair_input(prepared, required["auth_repair"])
        )
        receipt = self.auth_repair_receipt(repair)
        receipt["payload"]["auth_repair"]["env_var"] = "WRONG_TOKEN"

        result = verify_auth_repair_receipt(
            {"packet": repair["packet"], "receipt": receipt}
        )

        self.assertFalse(result["ok"])
        self.assertEqual("auth_repair_receipt_invalid", result["event"])
        self.assertIn("env_var does not match", " ".join(result["reasons"]))

    def test_auth_repair_receipt_rejects_undeclared_credential_material(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        required = verify_receipt(
            {
                "packet": prepared["packet"],
                "receipt": self.auth_repair_required_receipt(prepared),
            }
        )
        repair = prepare_auth_repair_handoff(
            self.auth_repair_input(prepared, required["auth_repair"])
        )
        receipt = self.auth_repair_receipt(repair)
        receipt["payload"]["auth_repair"]["access_token"] = "must-not-enter-play"

        result = verify_auth_repair_receipt(
            {"packet": repair["packet"], "receipt": receipt}
        )

        self.assertFalse(result["ok"])
        self.assertIn("undeclared fields", " ".join(result["reasons"]))

    def test_validated_repair_resumes_original_call_with_fresh_packet(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        required = verify_receipt(
            {
                "packet": prepared["packet"],
                "receipt": self.auth_repair_required_receipt(prepared),
            }
        )
        repair = prepare_auth_repair_handoff(
            self.auth_repair_input(prepared, required["auth_repair"])
        )
        repaired = verify_auth_repair_receipt(
            {"packet": repair["packet"], "receipt": self.auth_repair_receipt(repair)}
        )
        self.assertTrue(repaired["ok"])

        resume_input = self.input(available=["rote-using-adapters"])
        resume_input["inputs"] = {"query": "must be replaced from original"}
        resume_input["idempotency_key"] = "must-be-replaced"
        resume_input["auth_repair_resume"] = {
            "original_packet": prepared["packet"],
            "original_packet_sha256": prepared["packet_sha256"],
            "repair_packet": repair["packet"],
            "repair_receipt": self.auth_repair_receipt(repair),
            "repair_receipt_ref": repaired["receipt_ref"],
            "auth_repair": repaired["auth_repair"],
        }
        resumed = prepare_handoff(resume_input)

        self.assertTrue(resumed["ok"])
        self.assertNotEqual(prepared["packet_sha256"], resumed["packet_sha256"])
        self.assertEqual(prepared["packet"]["inputs"], resumed["packet"]["inputs"])
        self.assertEqual(
            prepared["packet"]["idempotency_key"], resumed["packet"]["idempotency_key"]
        )
        self.assertEqual(prepared["packet_sha256"], resumed["packet"]["resume"]["original_packet_sha256"])
        self.assertEqual(repaired["receipt_ref"], resumed["packet"]["resume"]["repair_receipt_ref"])

    def test_resume_rejects_an_unvalidated_repair_receipt_reference(self) -> None:
        prepared = prepare_handoff(self.input(available=["rote-using-adapters"]))
        required = verify_receipt(
            {
                "packet": prepared["packet"],
                "receipt": self.auth_repair_required_receipt(prepared),
            }
        )
        repair = prepare_auth_repair_handoff(
            self.auth_repair_input(prepared, required["auth_repair"])
        )
        repair_receipt = self.auth_repair_receipt(repair)
        repaired = verify_auth_repair_receipt(
            {"packet": repair["packet"], "receipt": repair_receipt}
        )
        resume_input = self.input(available=["rote-using-adapters"])
        resume_input["auth_repair_resume"] = {
            "original_packet": prepared["packet"],
            "original_packet_sha256": prepared["packet_sha256"],
            "repair_packet": repair["packet"],
            "repair_receipt": repair_receipt,
            "repair_receipt_ref": "fabricated-receipt-reference",
            "auth_repair": repaired["auth_repair"],
        }

        with self.assertRaisesRegex(ValueError, "receipt reference does not match"):
            prepare_handoff(resume_input)

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
