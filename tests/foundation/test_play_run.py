from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from scripts.lib.play.play_run import PlayRunError, execute


URI = "https://play.modiqo.ai/modiqo/hello@0.1.0"
EXACT = "modiqo/hello@0.1.0"


def payload(reference: str = URI) -> dict:
    parameters = {"region": "us"}
    return {
        "match": {"reference": reference},
        "inspection": {
            "exact_reference": EXACT,
            "disclosure_sha256": "a" * 64,
            "local_change": "none",
        },
        "request": {"parameters": parameters},
        "output_policy": {"mode": "detailed"},
        "auth_repair": {
            "original_packet": {
                "exact_reference": EXACT,
                "disclosure_sha256": "a" * 64,
                "parameters": parameters,
            },
            "original_packet_sha256": "b" * 64,
        },
    }


class UniversalPlayRunTest(unittest.TestCase):
    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_uses_approved_uri_once_and_preserves_output(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="hello output\n", stderr=""
        )

        result = execute(payload())

        self.assertEqual("play_run_ready", result["event"])
        self.assertEqual(URI, result["target"])
        self.assertEqual("hello output\n", result["output"]["primary"])
        self.assertEqual("full", result["output"]["detail"])
        run.assert_called_once()
        arguments = run.call_args.args[0]
        self.assertEqual(
            ["/usr/bin/rote", "play", "run", URI, "region=us", "--yes"],
            arguments,
        )

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_non_uri_selection_uses_exact_registry_reference(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="result", stderr=""
        )

        result = execute(payload("modiqo/hello"))

        self.assertEqual(EXACT, result["target"])
        self.assertEqual(EXACT, run.call_args.args[0][3])

    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_packet_mismatch_blocks_before_execution(self, run) -> None:
        request = payload()
        request["auth_repair"]["original_packet"]["disclosure_sha256"] = "c" * 64

        with self.assertRaisesRegex(PlayRunError, "digest differs"):
            execute(request)

        run.assert_not_called()

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_failure_returns_typed_drift_without_retry(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="one failure"
        )

        result = execute(payload())

        self.assertEqual("play_drifted", result["event"])
        self.assertEqual("one failure", result["reason"])
        run.assert_called_once()

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_structured_auth_failure_routes_to_adapter_config(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr='{"auth_repair":{"adapter_id":"github","env_var":"GITHUB_TOKEN","classified_rung":"static","distinguishing_error":"expired"}}',
        )

        result = execute(payload())

        self.assertEqual("play_auth_repair_required", result["event"])
        self.assertEqual("rote-adapter-config", result["auth_repair"]["owner"])
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
