from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.certificate import (
    CertificatePresentationError,
    build_certificate_presentation,
)
from play.digest_state import stable_sha


class CertificatePresentationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.objects = self.home / "births" / "objects"
        self.objects.mkdir(parents=True)
        self.record = {
            "schema": "play.birth/v1",
            "captured_at": "2026-08-06T12:00:00+00:00",
            "workspace": {"name": "pricing-exploration"},
            "flow": {
                "name": "modiqo-pricing-grid",
                "description": "Compare pricing choices.",
                "fingerprint": "flow-fingerprint",
            },
            "journey": {
                "commands": 5,
                "responses": 4,
                "duration_seconds": 42.5,
                "dependency_edges": [{"command_sequence": 2}],
                "modalities": ["adapter", "shell"],
                "outcomes": {
                    "total": 5,
                    "successes": 3,
                    "errors": 1,
                    "unknown": 1,
                },
            },
            "sources": {"trace": "rote-trace-deps-json"},
        }
        self.sha = stable_sha(self.record)
        (self.objects / f"{self.sha}.json").write_text(json.dumps(self.record))
        self.exact_reference = "daily-chores/modiqo-pricing-grid@0.0.1"
        self.content_hash = "registry-content-hash"
        index = {
            "schema": "play.birth-index/v1",
            "by_birth_sha": {
                self.sha: {
                    "flow_name": "modiqo-pricing-grid",
                    "flow_fingerprint": "flow-fingerprint",
                    "captured_at": self.record["captured_at"],
                    "exact_references": [self.exact_reference],
                    "bindings": {
                        self.exact_reference: {
                            "registry_content_hash": self.content_hash,
                            "author": "Chetan",
                            "author_status": "available",
                        }
                    },
                }
            },
            "by_exact_reference": {self.exact_reference: self.sha},
            "by_flow_fingerprint": {"flow-fingerprint": self.sha},
            "by_registry_content_hash": {self.content_hash: self.sha},
        }
        (self.home / "births" / "index.json").write_text(json.dumps(index))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def payload(self, *, visibility: str = "public") -> dict:
        play_uri = (
            "https://play.modiqo.ai/daily-chores/modiqo-pricing-grid@0.0.1"
            if visibility == "public"
            else None
        )
        return {
            "birth": {
                "sha256": self.sha,
                "flow_fingerprint": "flow-fingerprint",
                "exact_reference": self.exact_reference,
                "registry_content_hash": self.content_hash,
                "binding_ref": self.exact_reference,
            },
            "publication": {
                "title": "Modiqo Pricing Grid",
                "description": "Compare pricing choices.",
                "canonical_reference": "daily-chores/modiqo-pricing-grid",
                "visibility": visibility,
                "owner": "daily-chores",
                "content_hash": self.content_hash,
                "uri": play_uri,
                "install_uri": (
                    "https://play.modiqo.ai/install?play=daily-chores/modiqo-pricing-grid@0.0.1"
                    if visibility == "public"
                    else None
                ),
            },
            "play": {"version": "0.0.1"},
            "publication_validation": {
                "credential_status": "verified" if visibility == "public" else "not_required",
                "smoke_status": "verified" if visibility == "public" else "not_required",
                "smoke_exact_reference": play_uri,
                "smoke_ns": 12_500_000 if visibility == "public" else None,
            },
            "exploration": {"human_name": "chetan"},
            "onboarding": {"email_handle": None},
        }

    def test_public_certificate_visualizes_trace_uri_copy_and_farewell(self) -> None:
        result = build_certificate_presentation(self.payload(), home=self.home)

        self.assertEqual("play.birth-certificate-presentation/v1", result["schema"])
        self.assertTrue(result["birth"]["certificate_presented"])
        self.assertEqual(3, result["birth"]["trace_learning"]["successes"])
        self.assertEqual(1, result["birth"]["trace_learning"]["errors"])
        self.assertIn("PLAY BIRTH CERTIFICATE · VERIFIED", result["presentation_markdown"])
        self.assertIn("Successes:", result["presentation_markdown"])
        self.assertIn(self.payload()["publication"]["uri"], result["presentation_markdown"])
        self.assertIn("[Modiqo Pricing Grid — Compare pricing choices.]", result["presentation_markdown"])
        self.assertIn("Associated credential contracts: **verified**", result["presentation_markdown"])
        self.assertIn("# 🚀 Play published and verified", result["presentation_markdown"])
        self.assertIn("## 📣 Share your Play", result["presentation_markdown"])
        self.assertIn("Dear chetan. It was a pleasure working with you", result["presentation_markdown"])
        self.assertIn("we did an excellent job", result["presentation_markdown"])
        self.assertLessEqual(len(result["publication"]["share_copy"]["x"]), 280)
        self.assertEqual(64, len(result["presentation_ref"]))
        self.assertGreaterEqual(result["birth"]["certificate_ns"], 0)

    def test_private_certificate_does_not_invent_public_links_or_share_copy(self) -> None:
        result = build_certificate_presentation(
            self.payload(visibility="private"), home=self.home
        )

        self.assertIn("private — no public URI", result["presentation_markdown"])
        self.assertNotIn("## 📣 Share your Play", result["presentation_markdown"])
        self.assertEqual(
            {"x": None, "linkedin": None}, result["publication"]["share_copy"]
        )

    def test_legacy_birth_without_outcomes_marks_every_command_unknown(self) -> None:
        del self.record["journey"]["outcomes"]
        legacy_sha = stable_sha(self.record)
        (self.objects / f"{legacy_sha}.json").write_text(json.dumps(self.record))
        index_path = self.home / "births" / "index.json"
        index = json.loads(index_path.read_text())
        metadata = index["by_birth_sha"].pop(self.sha)
        index["by_birth_sha"][legacy_sha] = metadata
        index["by_exact_reference"][self.exact_reference] = legacy_sha
        index["by_flow_fingerprint"]["flow-fingerprint"] = legacy_sha
        index["by_registry_content_hash"][self.content_hash] = legacy_sha
        index_path.write_text(json.dumps(index))
        payload = self.payload()
        payload["birth"]["sha256"] = legacy_sha

        result = build_certificate_presentation(payload, home=self.home)

        learning = result["birth"]["trace_learning"]
        self.assertEqual(0, learning["successes"])
        self.assertEqual(0, learning["errors"])
        self.assertEqual(5, learning["unknown"])

    def test_binding_content_hash_mismatch_fails_closed(self) -> None:
        payload = self.payload()
        payload["publication"]["content_hash"] = "different-hash"

        with self.assertRaisesRegex(CertificatePresentationError, "content hash"):
            build_certificate_presentation(payload, home=self.home)

    def test_typed_cli_emits_the_certificate_contract(self) -> None:
        completed = subprocess.run(
            [
                str(ROOT / "scripts" / "bin" / "play-certificate"),
                "--stdin",
                "--json",
                "--home",
                str(self.home),
            ],
            input=json.dumps(self.payload()),
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual("play.birth-certificate-presentation/v1", result["schema"])
        self.assertTrue(result["birth"]["certificate_presented"])


if __name__ == "__main__":
    unittest.main()
