from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.lib.play import play_run
from scripts.lib.play.play_run import (
    PlayRunError,
    _CredentialSnapshot,
    _credential_snapshot,
    execute,
)


URI = "https://play.modiqo.ai/modiqo/hello@0.1.0"
LATEST_URI = "https://play.modiqo.ai/modiqo/hello"
EXACT = "modiqo/hello@0.1.0"
LATEST = "modiqo/hello"

AUTH_PROTOCOLS = {
    "static": "paste a static credential",
    "oauth": "adapter OAuth reauthorization",
    "oauth_dcr": "browser OAuth with dynamic registration",
    "google_discovery": "browser Google authorization",
}


def payload(reference: str = URI) -> dict:
    parameters = {"region": "us"}
    return {
        "match": {"reference": reference},
        "inspection": {
            "exact_reference": EXACT,
            "disclosure_sha256": "a" * 64,
            "local_change": "none",
            "operations": [
                {
                    "name": "google_auth",
                    "target": "adapter/gmail",
                    "operation": "adapter.auth.ensure",
                }
            ],
        },
        "request": {"parameters": parameters},
        "output_policy": {
            "mode": "detailed",
            "preferred_presentation": "human",
            "max_inline_bytes": 200_000,
            "overflow": "artifact",
        },
        "authentication": {
            "original_packet": {
                "exact_reference": EXACT,
                "disclosure_sha256": "a" * 64,
                "parameters": parameters,
            },
            "original_packet_sha256": "b" * 64,
        },
    }


def auth_markers(
    protocol: str,
    *,
    adapter: str = "crucible",
    credential: str = "ADAPTER_CRUCIBLE_TOKEN",
    adapter_calls_started: bool = False,
) -> str:
    return "\n".join(
        (
            "@@status",
            "error: authentication required",
            "@@authentication",
            f"Adapter: {adapter}",
            f"Credential: {credential}",
            "State: missing",
            f"Protocol: {AUTH_PROTOCOLS[protocol]}",
            "Authentication interaction: browser",
            "Network required: yes",
            "Remediation: retry in an interactive terminal to authorize",
            f"Adapter calls started: {str(adapter_calls_started).lower()}",
            "@@next",
            "- retry interactively",
        )
    )


def auth_prose(protocol: str) -> str:
    return "\n".join(
        (
            "Authentication required",
            "  Adapter: crucible",
            "  Credential: ADAPTER_CRUCIBLE_TOKEN",
            "  State: missing",
            f"  Protocol: {AUTH_PROTOCOLS[protocol]}",
            "  Authentication interaction: browser",
            "  Network required: yes",
            "  Remediation: retry in an interactive terminal to authorize",
            "  Adapter calls started: false",
        )
    )


def auth_json(protocol: str) -> str:
    return __import__("json").dumps(
        {
            "schema": 1,
            "ok": False,
            "data": {
                "play_auth_required": {
                    "schema": "play.auth-required/v1",
                    "adapter": "crucible",
                    "auth_type": "bearer",
                    "protocol": protocol,
                    "credential": "ADAPTER_CRUCIBLE_TOKEN",
                    "state": "missing",
                    "remedy": "browser_authorize",
                    "automatic_authorization": True,
                    "required_capability": "browser_loopback",
                    "interactive_required": True,
                    "authentication_interaction": "browser",
                    "interaction_mode": "non_interactive",
                    "network_required": True,
                    "remediation": "retry in an interactive terminal to authorize",
                    "adapter_calls_started": False,
                }
            },
        }
    )


class UniversalPlayRunTest(unittest.TestCase):
    def setUp(self) -> None:
        def missing_credential(
            _executable: str,
            adapter_id: str,
            expected_env: str,
            _environment: dict[str, str],
        ) -> _CredentialSnapshot:
            return _CredentialSnapshot(
                adapter_id=adapter_id,
                expected_env=expected_env,
                declared_env=expected_env,
                token_present=False,
                token_unreadable=False,
                healthy=False,
                health_state="missing",
                signature=f"missing:{adapter_id}:{expected_env}",
            )

        self.credential_snapshot = patch(
            "scripts.lib.play.play_run._credential_snapshot",
            side_effect=missing_credential,
        )
        self.credential_snapshot_mock = self.credential_snapshot.start()
        self.addCleanup(self.credential_snapshot.stop)

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_versioned_uri_executes_latest_unversioned_selector_once(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="hello output\n", stderr=""
        )

        result = execute(payload())

        self.assertEqual("play_run_ready", result["event"])
        self.assertEqual(LATEST_URI, result["target"])
        self.assertEqual("hello output\n", result["output"]["primary"])
        self.assertEqual("full", result["output"]["detail"])
        run.assert_called_once()
        arguments = run.call_args.args[0]
        self.assertEqual(
            ["/usr/bin/rote", "play", "run", LATEST_URI, "region=us", "--yes"],
            arguments,
        )
        self.assertEqual("structured", run.call_args.kwargs["env"]["ROTE_OUTPUT_MODE"])
        self.assertEqual("1", run.call_args.kwargs["env"]["ROTE_FLOW_PROGRESS"])

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_non_uri_selection_uses_latest_registry_reference(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="result", stderr=""
        )

        result = execute(payload("modiqo/hello"))

        self.assertEqual(LATEST, result["target"])
        self.assertEqual(LATEST, run.call_args.args[0][3])

    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_packet_mismatch_blocks_before_execution(self, run) -> None:
        request = payload()
        request["authentication"]["original_packet"]["disclosure_sha256"] = "c" * 64

        with self.assertRaisesRegex(PlayRunError, "digest differs"):
            execute(request)

        run.assert_not_called()

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_generic_failure_blocks_with_rotes_own_words_not_drift(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="one failure"
        )

        result = execute(payload())

        self.assertEqual("action_blocked", result["event"])
        self.assertEqual("one failure", result["reason"])
        self.assertTrue(result["recoverable"])
        run.assert_called_once()

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_drift_event_is_reserved_for_drift_evidence(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="artifact hash mismatch after pull"
        )

        result = execute(payload())

        self.assertEqual("play_drifted", result["event"])

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_registry_login_failure_names_its_remedy(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="@@status\nerror: Not logged in\n@@next\n- rote login"
        )

        result = execute(payload())

        self.assertEqual("action_blocked", result["event"])
        self.assertIn("rote login", result["reason"])
        self.assertIn("retry this exact Play", result["reason"])

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run._invoke_authenticated")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_auth_ensure_owns_browser_authentication_without_specialist(
        self, run, authenticated, _which
    ) -> None:
        authenticated.side_effect = lambda arguments, environment, directory, *_: (
            play_run._invoke(
                arguments,
                environment,
                directory,
                suffix="authenticated",
                terminal_stdin=True,
            )
        )
        for protocol in ("oauth", "oauth_dcr", "google_discovery"):
            with self.subTest(protocol=protocol):
                terminal_stdin: list[bool] = []

                def invoke(*_args, **kwargs):
                    stdin = kwargs.get("stdin")
                    terminal_stdin.append(
                        isinstance(stdin, int) and os.isatty(stdin)
                    )
                    if len(terminal_stdin) == 1:
                        return subprocess.CompletedProcess(
                            args=[], returncode=1, stdout="", stderr=auth_markers(protocol)
                        )
                    return subprocess.CompletedProcess(
                        args=[], returncode=0, stdout="authenticated output", stderr=""
                    )

                run.side_effect = invoke

                result = execute(payload())

                self.assertEqual("play_run_ready", result["event"])
                self.assertEqual([False, True], terminal_stdin)
                self.assertEqual(2, run.call_count)
                run.reset_mock(side_effect=True)

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_legacy_play_without_auth_ensure_routes_typed_auth_to_specialist(
        self, run, _which
    ) -> None:
        for protocol in AUTH_PROTOCOLS:
            with self.subTest(protocol=protocol):
                run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr=auth_json(protocol)
                )
                request = payload()
                request["inspection"]["operations"] = []

                result = execute(request)

                self.assertEqual("play_authentication_required", result["event"])
                self.assertEqual(protocol, result["authentication"]["classified_rung"])
                self.assertEqual("rote-adapter-config", result["authentication"]["owner"])
                run.reset_mock()

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_auth_ensure_static_token_uses_out_of_band_specialist_path(
        self, run, _which
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=auth_markers("static")
        )

        result = execute(payload())

        self.assertEqual("play_authentication_required", result["event"])
        self.assertEqual("static", result["authentication"]["classified_rung"])
        self.assertEqual("ADAPTER_CRUCIBLE_TOKEN", result["authentication"]["env_var"])
        self.assertEqual("rote-adapter-config", result["authentication"]["owner"])
        self.assertEqual(1, run.call_count)

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_static_done_verifies_exact_manifest_key_then_retries_once(
        self, run, _which
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="GitHub contributors", stderr=""
        )
        self.credential_snapshot_mock.side_effect = None
        self.credential_snapshot_mock.return_value = _CredentialSnapshot(
            adapter_id="github",
            expected_env="GITHUB_TOKEN",
            declared_env="GITHUB_TOKEN",
            token_present=True,
            token_unreadable=False,
            healthy=True,
            health_state="ready",
            signature="healthy-github-token",
        )
        request = payload("modiqo/list-top-committers")
        request["authentication"].update(
            {
                "status": "authenticating",
                "adapter_id": "github",
                "env_var": "GITHUB_TOKEN",
                "classified_rung": "static",
                "distinguishing_error": "missing: credential `GITHUB_TOKEN` is missing",
            }
        )

        result = execute(request)

        self.assertEqual("play_run_ready", result["event"])
        self.assertEqual("GitHub contributors", result["output"]["primary"])
        self.credential_snapshot_mock.assert_called_once()
        snapshot_args = self.credential_snapshot_mock.call_args.args
        self.assertEqual("github", snapshot_args[1])
        self.assertEqual("GITHUB_TOKEN", snapshot_args[2])
        run.assert_called_once()

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_static_done_with_missing_exact_key_returns_to_auth_offer_without_run(
        self, run, _which
    ) -> None:
        request = payload("modiqo/list-top-committers")
        request["authentication"].update(
            {
                "status": "authenticating",
                "adapter_id": "github",
                "env_var": "GITHUB_TOKEN",
                "classified_rung": "static",
                "distinguishing_error": "missing: credential `GITHUB_TOKEN` is missing",
            }
        )

        result = execute(request)

        self.assertEqual("play_authentication_required", result["event"])
        self.assertEqual("github", result["authentication"]["adapter_id"])
        self.assertEqual("GITHUB_TOKEN", result["authentication"]["env_var"])
        self.assertIn("not present and healthy", result["authentication"]["distinguishing_error"])
        self.credential_snapshot_mock.assert_called_once()
        run.assert_not_called()

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run._invoke_authenticated")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_notion_and_crucible_oauth_dcr_remain_play_owned(
        self, run, authenticated, _which
    ) -> None:
        authenticated.side_effect = lambda arguments, environment, directory, *_: (
            play_run._invoke(
                arguments,
                environment,
                directory,
                suffix="authenticated",
                terminal_stdin=True,
            )
        )
        adapters = (
            ("notion-mcp", "ADAPTER_NOTION_MCP_TOKEN"),
            ("crucible", "ADAPTER_CRUCIBLE_TOKEN"),
        )
        for adapter, credential in adapters:
            with self.subTest(adapter=adapter):
                run.side_effect = [
                    subprocess.CompletedProcess(
                        args=[],
                        returncode=1,
                        stdout="",
                        stderr=auth_markers(
                            "oauth_dcr", adapter=adapter, credential=credential
                        ),
                    ),
                    subprocess.CompletedProcess(
                        args=[], returncode=0, stdout=f"{adapter} output", stderr=""
                    ),
                ]

                result = execute(payload())

                self.assertEqual("play_run_ready", result["event"])
                self.assertNotIn("authentication", result)
                self.assertEqual(2, run.call_count)
                run.reset_mock(side_effect=True)

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_thread_otter_static_bearer_uses_out_of_band_specialist_path(
        self, run, _which
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr=auth_markers(
                "static", adapter="thread-otter", credential="THREAD_OTTER_TOKEN"
            ),
        )

        result = execute(payload())

        self.assertEqual("play_authentication_required", result["event"])
        self.assertEqual("thread-otter", result["authentication"]["adapter_id"])
        self.assertEqual("THREAD_OTTER_TOKEN", result["authentication"]["env_var"])
        self.assertEqual("static", result["authentication"]["classified_rung"])
        self.assertEqual(1, run.call_count)

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_thread_otter_resumes_when_exact_bearer_key_is_confirmed(
        self, run, _which
    ) -> None:
        run.side_effect = [
            subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr=auth_markers(
                    "static", adapter="thread-otter", credential="THREAD_OTTER_TOKEN"
                ),
            ),
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Thread Otter results", stderr=""
            ),
        ]
        self.credential_snapshot_mock.side_effect = None
        self.credential_snapshot_mock.return_value = _CredentialSnapshot(
            adapter_id="thread-otter",
            expected_env="THREAD_OTTER_TOKEN",
            declared_env="THREAD_OTTER_TOKEN",
            token_present=True,
            token_unreadable=False,
            healthy=True,
            health_state="ready",
            signature="healthy-thread-otter-token",
        )

        result = execute(payload())

        self.assertEqual("play_run_ready", result["event"])
        self.assertEqual("Thread Otter results", result["output"]["primary"])
        self.assertEqual(2, run.call_count)

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_authentication_blocks_when_manifest_and_failure_keys_differ(
        self, run, _which
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr=auth_markers(
                "static", adapter="thread-otter", credential="THREAD_OTTER_TOKEN"
            ),
        )
        self.credential_snapshot_mock.side_effect = None
        self.credential_snapshot_mock.return_value = _CredentialSnapshot(
            adapter_id="thread-otter",
            expected_env="THREAD_OTTER_TOKEN",
            declared_env="WRONG_TOKEN",
            token_present=False,
            token_unreadable=False,
            healthy=False,
            health_state="missing",
            signature="mismatch",
        )

        result = execute(payload())

        self.assertEqual("action_blocked", result["event"])
        self.assertIn("adapter thread-otter declares WRONG_TOKEN", result["reason"])
        self.assertIn("requested THREAD_OTTER_TOKEN", result["reason"])
        self.assertEqual(1, run.call_count)

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_legacy_play_prose_auth_failure_uses_compatibility_path(
        self, run, _which
    ) -> None:
        for protocol in AUTH_PROTOCOLS:
            with self.subTest(protocol=protocol):
                run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr=auth_prose(protocol)
                )

                request = payload()
                request["inspection"]["operations"] = []
                result = execute(request)

                self.assertEqual("play_authentication_required", result["event"])
                self.assertEqual(protocol, result["authentication"]["classified_rung"])
                run.reset_mock()

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run._invoke_authenticated")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_auth_ensure_failure_never_falls_back_to_specialist(
        self, run, authenticated, _which
    ) -> None:
        authenticated.side_effect = lambda arguments, environment, directory, *_: (
            play_run._invoke(
                arguments,
                environment,
                directory,
                suffix="authenticated",
                terminal_stdin=True,
            )
        )
        run.side_effect = [
            subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=auth_markers("google_discovery")
            ),
            subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=auth_markers("google_discovery")
            ),
        ]

        result = execute(payload())

        self.assertEqual("action_blocked", result["event"])
        self.assertNotIn("authentication", result)
        self.assertEqual(2, run.call_count)

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_unknown_auth_protocol_fails_closed(self, run, _which) -> None:
        output = auth_markers("oauth_dcr").replace(
            AUTH_PROTOCOLS["oauth_dcr"], "future magic auth"
        )
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=output
        )

        result = execute(payload())

        self.assertEqual("action_blocked", result["event"])
        self.assertIn("future magic auth", result["reason"])

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_auth_after_adapter_calls_does_not_enter_repair_loop(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr=auth_markers("oauth_dcr", adapter_calls_started=True),
        )

        result = execute(payload())

        self.assertEqual("action_blocked", result["event"])

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_large_output_is_bounded_and_preserved_as_private_artifact(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="é" * 100, stderr=""
        )
        request = payload()
        request["output_policy"]["max_inline_bytes"] = 21

        with __import__("tempfile").TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"PLAY_STATE_HOME": directory}):
                result = execute(request)

        self.assertTrue(result["output"]["truncated"])
        self.assertLessEqual(len(result["output"]["primary"].encode()), 21)
        self.assertTrue(result["output"]["full_output_ref"].startswith("file:"))
        self.assertEqual(
            [result["output"]["full_output_ref"]], result["artifact_refs"]
        )


class CredentialHandoffTest(unittest.TestCase):
    @patch("scripts.lib.play.play_run.run_json")
    def test_snapshot_compares_manifest_key_with_exact_token_inventory_name(
        self, run_json_mock
    ) -> None:
        run_json_mock.side_effect = [
            {
                "adapters": [
                    {
                        "id": "notion-mcp",
                        "health": {
                            "token_env": "ADAPTER_NOTION_MCP_TOKEN",
                            "state": "fresh",
                            "healthy": True,
                        },
                    }
                ]
            },
            [
                {
                    "name": "ADAPTER_NOTION_MCP_TOKEN",
                    "type": "oauth2",
                    "created": "2026-08-18",
                    "expires_in": "59m",
                    "refresh": "auto",
                    "refresh_state": "auto-rotating",
                    "is_dcr": True,
                    "unreadable": False,
                }
            ],
        ]

        snapshot = _credential_snapshot(
            "/usr/bin/rote",
            "notion-mcp",
            "ADAPTER_NOTION_MCP_TOKEN",
            {},
        )

        self.assertTrue(snapshot.usable)
        self.assertEqual("ADAPTER_NOTION_MCP_TOKEN", snapshot.declared_env)
        self.assertEqual(
            [
                "/usr/bin/rote",
                "adapter",
                "list",
                "notion-mcp",
                "--json",
                "--health",
            ],
            run_json_mock.call_args_list[0].args[0],
        )
        self.assertEqual(
            ["/usr/bin/rote", "token", "list", "--json"],
            run_json_mock.call_args_list[1].args[0],
        )

    def test_dcr_browser_completion_resumes_on_verified_manifest_token_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "rote"
            state_path = root / "credential-ready"
            count_path = root / "run-count"
            authentication = auth_markers(
                "oauth_dcr",
                adapter="notion-mcp",
                credential="ADAPTER_NOTION_MCP_TOKEN",
            )
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env python3
                    import json
                    import os
                    from pathlib import Path
                    import sys

                    state = Path(os.environ["FAKE_CREDENTIAL_STATE"])
                    count_file = Path(os.environ["FAKE_RUN_COUNT"])
                    arguments = sys.argv[1:]
                    if arguments[:2] == ["play", "run"]:
                        count = int(count_file.read_text()) + 1 if count_file.exists() else 1
                        count_file.write_text(str(count))
                        if count == 1:
                            sys.stderr.write({authentication!r})
                            raise SystemExit(1)
                        if count == 2:
                            state.write_text("ready")
                            sys.stdin.readline()
                        print("Notion search returned 2 matching pages")
                        raise SystemExit(0)
                    if arguments[:2] == ["adapter", "list"]:
                        ready = state.exists()
                        print(json.dumps({{
                            "adapters": [{{
                                "id": "notion-mcp",
                                "health": {{
                                    "token_env": "ADAPTER_NOTION_MCP_TOKEN",
                                    "state": "fresh" if ready else "missing",
                                    "healthy": ready,
                                }},
                            }}],
                        }}))
                        raise SystemExit(0)
                    if arguments[:2] == ["token", "list"]:
                        tokens = []
                        if state.exists():
                            tokens.append({{
                                "name": "ADAPTER_NOTION_MCP_TOKEN",
                                "type": "oauth2",
                                "created": "2026-08-18T16:00:00Z",
                                "expires_in": "59m",
                                "refresh": "auto",
                                "refresh_state": "auto-rotating",
                                "is_dcr": True,
                                "unreadable": False,
                            }})
                        print(json.dumps(tokens))
                        raise SystemExit(0)
                    raise SystemExit(2)
                    """
                )
            )
            executable.chmod(0o755)
            environment = {
                "FAKE_CREDENTIAL_STATE": str(state_path),
                "FAKE_RUN_COUNT": str(count_path),
                "PLAY_AUTH_POLL_SECONDS": "0.02",
                "PLAY_AUTH_TIMEOUT_SECONDS": "5",
            }
            with (
                patch("scripts.lib.play.play_run.shutil.which", return_value=str(executable)),
                patch.dict(os.environ, environment),
            ):
                result = execute(payload())
            run_count = count_path.read_text()

        self.assertEqual("play_run_ready", result["event"], result)
        self.assertEqual(
            "Notion search returned 2 matching pages\n",
            result["output"]["primary"],
        )
        self.assertEqual("3", run_count)


if __name__ == "__main__":
    unittest.main()
