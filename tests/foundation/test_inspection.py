from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.inspection import InspectionError, normalize_inspection, render_markdown


def inspected_payload(*, eligible: bool = True, local_decision: str = "install_required") -> dict:
    return {
        "identity": {
            "owner": "alpha",
            "name": "report",
            "version": "1.2.0",
            "description": "Builds the customer report.",
            "visibility": "private",
        },
        "archive": {"content_hash": "abc123"},
        "execution": {
            "play_run_eligible": eligible,
            "blockers": [] if eligible else ["steps are not runnable"],
        },
        "parameters": [
            {"name": "days", "type": "integer", "required": False, "default": "7"}
        ],
        "steps": [
            {
                "name": "fetch",
                "target": "adapter/example",
                "operation": "exec",
                "endpoint": "adapter/example",
                "method": "exec",
            }
        ],
        "requirements": {
            "endpoints": [{"endpoint": "adapter/example", "mcp_fingerprint": "mcp_123"}],
            "runtimes": [],
            "npm_packages": [],
            "browser_binaries": [],
            "browser_auth": {"status": "unknown", "dependencies": []},
            "adapter_credentials": {"status": "unknown"},
            "write_permissions": [],
            "sensitivity": {"status": "unknown"},
        },
        "host": {
            "runtimes": [],
            "browsers": [],
            "endpoints": [{"name": "adapter/example", "status": "present"}],
            "adapters": [{"name": "example", "status": "present"}],
            "daemon": "not_required",
        },
        "convergence": {
            "read_only": True,
            "play": {
                "local_state": "absent" if local_decision == "install_required" else "installed",
                "decision": local_decision,
                "reason": "the resolved play is not installed locally",
            },
            "adapters": [
                {
                    "adapter_id": "example",
                    "requirement": "adapter/example (mcp_123)",
                    "local_state": "receipt_verified",
                    "decision": "ready",
                    "reason": "verified",
                    "credential_demand": {
                        "status": "required",
                        "names": ["EXAMPLE_TOKEN"],
                        "protocols": ["oauth"],
                    },
                }
            ],
            "unsupported": [],
        },
    }


class InspectionTest(unittest.TestCase):
    def test_normalizes_exact_reference_dependencies_and_pull_requirement(self) -> None:
        disclosure = normalize_inspection("alpha/report", inspected_payload())
        self.assertEqual("play.run-disclosure/v1", disclosure["schema"])
        self.assertEqual("alpha/report@1.2.0", disclosure["exact_reference"])
        self.assertEqual("Builds the customer report.", disclosure["description"])
        self.assertEqual("install", disclosure["local_change"])
        self.assertTrue(disclosure["preflight"]["pull_or_install_required"])
        self.assertEqual("install", disclosure["preflight"]["local_change"])
        self.assertEqual(
            ["EXAMPLE_TOKEN"],
            disclosure["dependencies"]["adapter_checks"][0]["credential_demand"]["names"],
        )
        self.assertTrue(disclosure["approval"]["required"])
        self.assertEqual(64, len(disclosure["disclosure_sha256"]))

    def test_generic_adapter_operation_does_not_claim_read_only(self) -> None:
        disclosure = normalize_inspection("alpha/report", inspected_payload())
        self.assertEqual("operation_semantics_unknown", disclosure["effects"]["classification"])
        self.assertIn("do not prove", disclosure["effects"]["summary"])
        self.assertIn("Nothing has been installed", render_markdown(disclosure))

    def test_execution_blockers_disable_run_approval(self) -> None:
        disclosure = normalize_inspection("alpha/report", inspected_payload(eligible=False))
        self.assertFalse(disclosure["preflight"]["run_eligible"])
        self.assertFalse(disclosure["approval"]["allowed"])
        self.assertIn("steps are not runnable", render_markdown(disclosure))

    def test_missing_preflight_contract_fails_closed(self) -> None:
        with self.assertRaises(InspectionError):
            normalize_inspection("alpha/report", {"identity": {}})


if __name__ == "__main__":
    unittest.main()
