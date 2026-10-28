import io
import json
import os
import subprocess
import tempfile
import unittest
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from http.client import HTTPMessage
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from scripts.lib.play import search_transport as transport
from scripts.lib.play.commands import CommandError


class SearchTransportTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.env = patch.dict(os.environ, {"ROTE_HOME": self.home.name, "ROTE_REGISTRY_ENV": "", "PLAY_SEARCH_ENDPOINT": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = Path(self.home.name) / "registry/config.json"
        self.config.parent.mkdir()
        self.save()

    def save(self, url="https://roteprod.registry.modiqo.ai", token="secret"):
        self.config.write_text(json.dumps({"url": url, "access_token": token}))

    def search(self, **kwargs):
        return transport.request_search("Audit DNS without changes", public=kwargs.get("public", False), org=kwargs.get("org"), limit=5, timeout_seconds=10)

    @patch.object(transport, "run_rote")
    @patch.object(transport, "build_opener")
    def test_refresh_then_authenticated_request_preserves_constraints_and_groups(self, opener, run):
        def refresh(*args, **kwargs):
            self.save(token="refreshed")
            return subprocess.CompletedProcess([], 0, "", "")
        run.side_effect = refresh
        opener.return_value.open.return_value = io.BytesIO(b'{"registry":"production"}')
        self.search()
        run.assert_called_once()
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual("Bearer refreshed", request.get_header("Authorization"))
        self.assertEqual(transport.ENDPOINTS["production"], request.full_url)
        body = json.loads(request.data)
        self.assertEqual(["community", "personal", "organizations"], body["scopes"])
        self.assertEqual("Audit DNS without changes", body["query"])
        self.assertNotIn("secret", str(body))

    @patch.object(transport, "run_rote")
    @patch.object(transport, "build_opener")
    def test_public_is_anonymous_and_staging_cannot_mix_environments(self, opener, run):
        self.save(url="https://rotestaging.registry.modiqo.ai")
        opener.return_value.open.return_value = io.BytesIO(b'{"registry":"staging"}')
        self.search(public=True)
        run.assert_not_called()
        request = opener.return_value.open.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(transport.ENDPOINTS["staging"], request.full_url)
        self.assertEqual(["community"], json.loads(request.data)["scopes"])
        opener.return_value.open.return_value = io.BytesIO(b'{"registry":"production"}')
        with self.assertRaisesRegex(CommandError, "wrong registry"):
            self.search(public=True)

    @patch.object(transport, "run_rote", return_value=subprocess.CompletedProcess([], 77, "", "login required"))
    @patch.object(transport, "build_opener")
    def test_missing_login_never_downgrades_or_calls_worker(self, opener, run):
        with self.assertRaises(CommandError):
            self.search()
        opener.assert_not_called()

    @patch.object(transport, "run_rote", return_value=subprocess.CompletedProcess([], 0, "", ""))
    @patch.object(transport, "build_opener")
    def test_org_filter_and_http_errors_never_echo_secrets(self, opener, run):
        opener.return_value.open.return_value = io.BytesIO(b'{"registry":"production"}')
        self.search(org="acme")
        body = json.loads(opener.return_value.open.call_args.args[0].data)
        self.assertEqual(["organizations"], body["scopes"])
        self.assertEqual("acme", body["org"])
        opener.return_value.open.side_effect = HTTPError("https://example.test", 401, "secret", HTTPMessage(), io.BytesIO(b"secret"))
        with self.assertRaises(CommandError) as error:
            self.search()
        self.assertNotIn("secret", str(error.exception))
        self.assertIn("401", str(error.exception))

    @patch.object(transport, "run_rote")
    @patch.object(transport, "build_opener")
    def test_custom_registry_bad_org_and_override_do_not_leak_saved_token(self, opener, run):
        self.save(url="https://attacker.example")
        with self.assertRaises(CommandError):
            self.search()
        with self.assertRaises(CommandError):
            self.search(org="../bad")
        run.assert_not_called()
        opener.assert_not_called()
        with patch.dict(os.environ, {"ROTE_REGISTRY_ENV": "production"}):
            self.assertNotIn("access_token", transport.registry_config())

    def test_redirect_handler_refuses_token_forwarding(self):
        self.assertIsNone(transport.NoRedirects().redirect_request(Mock(), io.BytesIO(), 307, "redirect", HTTPMessage(), "https://attacker.example"))

    def local_config(self, url="http://127.0.0.1:54321"):
        self.config.write_text(json.dumps({"url": url, "access_token": "local-secret"}))

    @patch.object(transport, "run_rote", return_value=subprocess.CompletedProcess([], 0, "", ""))
    @patch.object(transport, "build_opener")
    def test_local_search_routes_both_scopes_and_binds_owned_url(self, opener, run):
        self.local_config()
        with patch.dict(os.environ, {"PLAY_SEARCH_ENDPOINT": "http://127.0.0.1:8765/v1/search"}):
            for public in (True, False):
                opener.return_value.open.return_value = io.BytesIO(b'{"registry":"test","registry_url":"http://127.0.0.1:54321"}')
                self.search(public=public)
                request = opener.return_value.open.call_args.args[0]
                self.assertEqual("http://127.0.0.1:8765/v1/search", request.full_url)
                self.assertEqual("test", request.get_header("X-modiqo-registry-environment"))
                self.assertEqual(None if public else "Bearer local-secret", request.get_header("Authorization"))
            run.assert_called_once()
            opener.return_value.open.return_value = io.BytesIO(b'{"registry":"test","registry_url":"http://127.0.0.1:54322"}')
            with self.assertRaisesRegex(CommandError, "URL binding"):
                self.search(public=True)

    @patch.object(transport, "run_rote")
    @patch.object(transport, "build_opener")
    def test_refresh_cannot_change_exact_registry_binding(self, opener, run):
        self.local_config()
        def refresh(*args, **kwargs):
            self.local_config("http://127.0.0.1:54322")
            return subprocess.CompletedProcess([], 0, "", "")
        run.side_effect = refresh
        with patch.dict(os.environ, {"PLAY_SEARCH_ENDPOINT": "http://127.0.0.1:8765/v1/search"}):
            with self.assertRaisesRegex(CommandError, "No usable login"):
                self.search()
        opener.assert_not_called()

    @patch.object(transport, "run_rote")
    @patch.object(transport, "build_opener")
    def test_endpoint_and_local_configuration_fail_closed(self, opener, run):
        self.local_config()
        endpoints = (
            "http://remote.example/v1/search",
            "http://localhost/v1/search",
            "https://user:secret@example.com/v1/search",
            "https://example.com/v1/search?token=secret",
            "https://example.com/v1/search#fragment",
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, {"PLAY_SEARCH_ENDPOINT": endpoint}):
                with self.assertRaises(CommandError):
                    self.search()
        with self.assertRaises(CommandError):
            self.search(public=True)
        self.save(url="https://unknown.example")
        with patch.dict(os.environ, {"PLAY_SEARCH_ENDPOINT": "http://127.0.0.1:8765/v1/search"}):
            with self.assertRaises(CommandError):
                self.search(public=True)
        run.assert_not_called()
        opener.assert_not_called()

    @patch.object(transport, "build_opener")
    @patch.object(transport, "run_rote")
    def test_refresh_roundtrip_without_unknown_fields_retains_local_binding(self, run, opener):
        self.local_config()
        def refresh(*args, **kwargs):
            self.config.write_text(json.dumps({"url": "http://127.0.0.1:54321", "access_token": "refreshed-local", "refresh_token": "refresh"}))
            return subprocess.CompletedProcess([], 0, "", "")
        run.side_effect = refresh
        opener.return_value.open.return_value = io.BytesIO(b'{"registry":"test","registry_url":"http://127.0.0.1:54321"}')
        with patch.dict(os.environ, {"PLAY_SEARCH_ENDPOINT": "http://127.0.0.1:8765/v1/search"}):
            self.search()
            self.assertEqual("https://play.test.modiqo.ai/", transport.play_origin())
        self.assertEqual("Bearer refreshed-local", opener.return_value.open.call_args.args[0].get_header("Authorization"))


    def test_staging_origin_comes_from_actual_config_without_endpoint_override(self):
        self.save(url="https://rotestaging.registry.modiqo.ai")
        self.assertEqual("https://play.stg.modiqo.ai/", transport.play_origin())

    def test_https_custom_api_retains_hosted_registry_identity(self):
        with patch.dict(os.environ, {"PLAY_SEARCH_ENDPOINT": "https://owned.example/v1/search"}):
            self.assertEqual(
                ("production", "https://roteprod.registry.modiqo.ai", "https://owned.example/v1/search"),
                transport.search_binding(transport.registry_config()),
            )

    @patch.object(transport, "run_rote", return_value=subprocess.CompletedProcess([], 0, "", ""))
    def test_actual_loopback_http_transport(self, run):
        self.local_config()
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"registry":"test","registry_url":"http://127.0.0.1:54321"}')

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_port}/v1/search"
            with patch.dict(os.environ, {"PLAY_SEARCH_ENDPOINT": endpoint}):
                self.search()
                self.search(public=True)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        self.assertEqual(["/v1/search", "/v1/search"], [row[0] for row in requests])
        self.assertEqual(["Bearer local-secret", None], [row[1] for row in requests])
        self.assertEqual(["community"], requests[1][2]["scopes"])
