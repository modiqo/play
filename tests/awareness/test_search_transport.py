import io
import json
import os
import subprocess
import tempfile
import unittest
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
        self.env = patch.dict(os.environ, {"ROTE_HOME": self.home.name, "ROTE_REGISTRY_ENV": ""})
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
