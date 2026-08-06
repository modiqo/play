from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import cast


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.publication_gate import (
    PublicationGateError,
    smoke_publication,
    validate_credential_contracts,
)


def context() -> dict:
    return {
        "publication": {
            "canonical_reference": "chetan/list-my-github-repos",
            "uri": "https://play.modiqo.ai/chetan/list-my-github-repos@0.0.2",
            "visibility": "public",
        },
        "play": {"version": "0.0.2"},
        "request": {"parameters": {"sort": "updated", "per_page": 10}},
    }


def play_inspection(*, token_env: str = "GITHUB_API_TOKEN") -> dict:
    return {
        "schema": 1,
        "ok": True,
        "data": {
            "play_inspect": {
                "identity": {
                    "owner": "chetan",
                    "name": "list-my-github-repos",
                    "version": "0.0.2",
                    "visibility": "public",
                },
                "execution": {"play_run_eligible": True, "blockers": []},
                "convergence": {
                    "adapters": [
                        {
                            "adapter_id": "github",
                            "local_state": "receipt_verified",
                            "registry_candidates": ["chetan/github"],
                            "selected_candidate": "chetan/github",
                            "decision": "ready",
                            "credential_demand": {
                                "status": "required",
                                "names": [token_env],
                                "protocols": ["static"],
                            },
                        }
                    ]
                },
            }
        },
    }


def local_adapter(*, token_env: str = "GITHUB_API_TOKEN", version: str = "1.1.0") -> dict:
    return {
        "ok": True,
        "data": {
            "result": {
                "identity": {"id": "github", "version": version},
                "source": {"fingerprint": "mcp_github"},
                "authentication": {
                    "kind": "bearer",
                    "bindings": [{"kind": "bearer", "credential": token_env}],
                },
            }
        },
    }


def registry_adapter(*, token_env: str = "GITHUB_API_TOKEN") -> dict:
    return {
        "adapter": {"name": "github", "fingerprint": "mcp_github"},
        "version": {
            "version": "1.1.0",
            "manifest": {
                "id": "github",
                "version": "1.1.0",
                "fingerprint": "mcp_github",
                "auth": {"type": "bearer", "token_env": token_env},
            },
        },
    }


class PublicationCredentialGateTest(unittest.TestCase):
    def test_matching_provenance_and_token_contract_are_verified(self) -> None:
        result = validate_credential_contracts(
            context(),
            play_inspection(),
            lambda _: local_adapter(),
            lambda _: registry_adapter(),
        )
        self.assertTrue(result["ok"])
        self.assertEqual("verified", result["credential_status"])
        self.assertEqual(["GITHUB_API_TOKEN"], result["adapter_contracts"][0]["credential_names"])
        self.assertEqual("receipt_verified", result["adapter_contracts"][0]["provenance"])
        self.assertEqual(64, len(result["credential_contract_sha256"]))
        self.assertGreaterEqual(result["credential_check_ns"], 0)
        self.assertNotIn("token_value", str(result))

    def test_equal_fingerprint_does_not_hide_token_env_mismatch(self) -> None:
        with self.assertRaisesRegex(
            PublicationGateError, "credential environment-variable contract differs"
        ):
            validate_credential_contracts(
                context(),
                play_inspection(token_env="GITHUB_API_TOKEN"),
                lambda _: local_adapter(token_env="GITHUB_API_TOKEN"),
                lambda _: registry_adapter(token_env="GH_TOKEN"),
            )

    def test_unverified_provenance_fails_closed(self) -> None:
        inspected = play_inspection()
        check = inspected["data"]["play_inspect"]["convergence"]["adapters"][0]
        check["local_state"] = "fingerprint_match"
        with self.assertRaisesRegex(PublicationGateError, "receipt-verified provenance"):
            validate_credential_contracts(
                context(), inspected, lambda _: local_adapter(), lambda _: registry_adapter()
            )

    def test_version_mismatch_fails_closed(self) -> None:
        with self.assertRaisesRegex(PublicationGateError, "version differs"):
            validate_credential_contracts(
                context(),
                play_inspection(),
                lambda _: local_adapter(version="1.0.0"),
                lambda _: registry_adapter(),
            )


class PublicationSmokeGateTest(unittest.TestCase):
    def test_exact_uri_runs_with_parameters_from_an_isolated_tmp_directory(self) -> None:
        observed: dict[str, object] = {}

        def runner(command, working_directory):
            observed["command"] = list(command)
            observed["directory"] = working_directory
            self.assertTrue(working_directory.is_dir())
            return 0, '{"ok":true,"data":{"status":"complete"}}\n', ""

        result = smoke_publication(context(), runner)
        self.assertTrue(result["ok"])
        self.assertEqual("verified", result["smoke_status"])
        self.assertEqual(
            [
                "rote",
                "play",
                "run",
                "https://play.modiqo.ai/chetan/list-my-github-repos@0.0.2",
                "per_page=10",
                "sort=updated",
                "--yes",
            ],
            observed["command"],
        )
        directory = cast(Path, observed["directory"])
        self.assertEqual("/tmp", str(directory.parent))
        self.assertFalse(directory.exists())
        self.assertTrue(result["isolated_workdir"])
        self.assertEqual(64, len(result["smoke_output_sha256"]))
        self.assertGreaterEqual(result["smoke_ns"], 0)

    def test_missing_credential_failure_exposes_name_not_value(self) -> None:
        def runner(command, working_directory):
            return 1, "", "Play credential `GH_TOKEN` for adapter `github` is missing"

        result = smoke_publication(context(), runner)
        self.assertFalse(result["ok"])
        self.assertEqual("credential_missing", result["failure_class"])
        self.assertEqual(["GH_TOKEN"], result["credential_names"])
        self.assertNotIn("Play credential", str(result))

    def test_non_exact_public_uri_is_rejected_before_execution(self) -> None:
        payload = context()
        payload["publication"]["uri"] = "https://play.modiqo.ai/chetan/list-my-github-repos"
        with self.assertRaisesRegex(PublicationGateError, "exact published version"):
            smoke_publication(payload, lambda *_: self.fail("runner must not execute"))


if __name__ == "__main__":
    unittest.main()
