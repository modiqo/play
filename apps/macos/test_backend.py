"""Contract and failure-path tests. Never invoke real auth, installs, or invitations."""
import importlib.util
import importlib.machinery
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
spec = importlib.util.spec_from_file_location("mac_backend", HERE / "backend.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bridge = backend.Bridge(ROOT, self.root / "state")
        self.bridge.load_runtime()
        self.bridge.harnesses = Mock(return_value=[])
        self.bridge.require_identity = Mock(return_value={"state": "authenticated", "email": "owner@example.com", "userID": "owner"})
        self.bridge.rote = Mock(return_value="/fake/rote")
        self.command = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        self.addCleanup(patch.stopall)
        patch.object(backend, "command", self.command).start()
        patch.object(backend, "urlopen", side_effect=AssertionError("Unexpected network access")).start()
        patch.object(backend, "emit").start()

    def test_version_order_and_downgrade(self):
        self.assertGreater(backend.version_key("0.4.100"), backend.version_key("0.4.99"))
        self.assertEqual(backend.version_key("0.4.98+codex.20260924"), (0, 4, 98))
        with patch.object(self.bridge.bootstrap, "_installed_play_version", return_value="0.5.0"):
            with self.assertRaisesRegex(backend.UserError, "downgrades"):
                self.bridge.release_source("0.4.99")

    def test_bad_versions_never_download(self):
        for version in ["../0.4.99", "0.4.99;id", "main", "1.0.0-rc1", None]:
            with self.subTest(version=version), self.assertRaises(backend.UserError):
                self.bridge.release_source(version)

    def test_newer_marketplace_version_blocks_downgrade(self):
        self.bridge.harnesses.return_value = [{"installed": True, "version": "0.5.1+codex.local"}]
        with self.assertRaisesRegex(backend.UserError, "downgrades"):
            self.bridge.release_source("0.4.99")

    def archive(self, name, *, link=False):
        path = self.root / "test.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            entry = tarfile.TarInfo(name)
            if link:
                entry.type = tarfile.SYMTYPE
                entry.linkname = "/etc/passwd"
                archive.addfile(entry)
            else:
                entry.size = 2
                entry.mode = 0o755
                archive.addfile(entry, io.BytesIO(b"ok"))
        return path

    def test_archive_rejects_traversal_and_links(self):
        for name in ["root/../../escape", "/tmp/escape", "../escape"]:
            with self.subTest(name=name), self.assertRaises(backend.UserError):
                backend.secure_extract(self.archive(name), self.root / "out")
        with self.assertRaises(backend.UserError):
            backend.secure_extract(self.archive("root/link", link=True), self.root / "out")

    def test_archive_preserves_executable_and_strips_root(self):
        backend.secure_extract(self.archive("release/scripts/tool"), self.root / "out")
        target = self.root / "out/scripts/tool"
        self.assertEqual(target.read_text(), "ok")
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)

    def test_private_state_permissions(self):
        path = self.bridge.root / "metadata.json"
        backend.save_json(path, {"email": "test@example.com"})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.bridge.root.stat().st_mode & 0o777, 0o700)

    def test_auth_provider_allowlist(self):
        with self.assertRaises(backend.UserError):
            self.bridge.login({"provider": "google; id"})
        self.command.assert_not_called()

    def test_email_code_only_stdin_and_no_persisted_secret(self):
        from play import email_login
        backend.save_json(self.bridge.root / "email-attempt.json", {"email": "test@example.com", "sent_at": time.monotonic(), "failures": 0, "created": time.time()})
        with patch.object(email_login, "run_rote", return_value=subprocess.CompletedProcess([], 0, "", "")) as run, patch("play.identity.remember_login_provider"):
            self.bridge.email({"operation": "verify", "email": "test@example.com", "code": "123456"})
            self.assertNotIn("123456", " ".join(run.call_args.args[0]))
            self.assertEqual(run.call_args.kwargs["input"], "123456\n")
        self.assertFalse((self.bridge.root / "email-attempt.json").exists())

    def test_email_attempt_limit_and_expiry_survive_bridge_restart(self):
        from play import email_login
        path = self.bridge.root / "email-attempt.json"
        with patch.object(email_login, "run_rote") as run:
            backend.save_json(path, {"email": "test@example.com", "sent_at": time.monotonic(), "failures": 5, "created": time.time()})
            with self.assertRaisesRegex(backend.UserError, "new code"):
                self.bridge.email({"operation": "verify", "email": "test@example.com", "code": "123456"})
            backend.save_json(path, {"email": "test@example.com", "created": time.time() - 601})
            with self.assertRaisesRegex(backend.UserError, "expired"):
                self.bridge.email({"operation": "verify", "email": "test@example.com", "code": "123456"})
            run.assert_not_called()

    def test_email_resend_cooldown(self):
        from play import email_login
        backend.save_json(self.bridge.root / "email-attempt.json", {"email": "test@example.com", "sent_at": time.monotonic(), "failures": 0, "created": time.time()})
        with patch.object(email_login, "run_rote") as run, self.assertRaisesRegex(backend.UserError, "one minute"):
            self.bridge.email({"operation": "send", "email": "test@example.com"})
        run.assert_not_called()

    def test_organization_ownership_and_safe_arguments(self):
        self.command.return_value.stdout = json.dumps([{"id": "a", "slug": "ours", "display_name": "Our org", "owner_id": "owner"}, {"id": "b", "slug": "joined", "owner_id": "someone"}])
        rows = self.bridge.organizations({})["organizations"]
        self.assertEqual([x["owned"] for x in rows], [True, False])
        self.bridge.create_org({"slug": "company", "name": "Company $(do-not-run)"})
        self.assertEqual(self.command.call_args.args[0][-1], "Company $(do-not-run)")
        with self.assertRaises(backend.UserError):
            self.bridge.invite({"slug": "company", "email": "a@example.com", "role": "owner"})

    def test_invitation_role_and_uncertain_failure(self):
        self.bridge.invite({"slug": "company", "email": "a@example.com", "role": "admin"})
        self.assertEqual(self.command.call_args.args[0], ["/fake/rote", "registry", "org", "invite", "company", "a@example.com", "--role", "admin"])
        self.command.return_value.returncode = 1
        with self.assertRaisesRegex(backend.UserError, "pending invitations"):
            self.bridge.invite({"slug": "company", "email": "a@example.com", "role": "admin"})

    def test_search_uses_worker_and_preserves_uncertainty(self):
        from play import search
        rows = [{"exact_reference": "org/company/play@1", "name": "Review", "description": "Published Play", "uri": "https://www.modiqo.ai/feed", "group_id": "org:company", "group_label": "Company", "group_kind": "organization", "relevance_status": "uncertain", "primary_scope": "remote_private"}]
        with patch.object(search, "search_published", return_value={"complete": False, "results": rows}) as find:
            result = self.bridge.search({"query": "review a PR", "scope": "org", "org": "company"})
            self.assertEqual(find.call_args.kwargs["org"], "company")
            self.assertFalse(result["complete"])
            self.assertEqual(result["results"][0]["visibility"], "private")
            self.assertEqual(result["results"][0]["relevance"], "uncertain")
        self.command.assert_not_called()

    def test_unauthenticated_search_never_calls_worker(self):
        from play import search
        self.bridge.require_identity.side_effect = backend.UserError("Sign in")
        with patch.object(search, "search_published") as find, self.assertRaises(backend.UserError):
            self.bridge.search({"query": "review"})
        find.assert_not_called()

    def test_worker_rejected_identity_offers_sign_in_without_fallback(self):
        from play import search
        with patch.object(search, "search_published", side_effect=search.SearchError("Shared search failed (HTTP 401)")) as find:
            with self.assertRaises(backend.UserError) as error:
                self.bridge.search({"query": "review", "scope": "all"})
            self.assertEqual(error.exception.code, "signin")
            self.assertEqual(find.call_count, 1)

    def test_plan_requires_supported_harnesses(self):
        with self.assertRaises(backend.UserError):
            self.bridge.plan({"harnesses": ["shell;id"], "version": "0.4.99"})
        self.command.assert_not_called()

    def saved_plan(self, **changes):
        value = {"created": time.time(), "source": str(ROOT), "plan": {"plan_id": "reviewed", "selected_harnesses": ["claude"]}}
        value.update(changes)
        identifier = "a" * 32
        backend.save_json(self.bridge.root / "plans" / f"{identifier}.json", value)
        return {"approved": True, "planID": identifier}

    def test_expired_and_unapproved_plans_cannot_apply(self):
        for payload in [{"planID": "a" * 32}, self.saved_plan(created=time.time() - 901)]:
            with self.assertRaises(backend.UserError):
                self.bridge.install(payload)
        self.command.assert_not_called()

    def test_stale_plan_cannot_apply(self):
        fake = SimpleNamespace(build_plan=Mock(return_value={"plan_id": "changed"}), apply=Mock())
        with patch.object(self.bridge, "runtime_for_source", return_value=fake), self.assertRaisesRegex(backend.UserError, "changed since review"):
            self.bridge.install(self.saved_plan())
        fake.apply.assert_not_called()

    def test_external_plan_source_rejected(self):
        with self.assertRaisesRegex(backend.UserError, "outside"):
            self.bridge.install(self.saved_plan(source="/tmp/untrusted"))

    def test_runtime_survives_app_removal(self):
        runtime = self.root / "app/runtime"
        (runtime / "python/bin").mkdir(parents=True)
        (runtime / "python/bin/python3").write_text("python fixture")
        (runtime / "bin").mkdir()
        backend.save_json(runtime / "runtime.json", {"version": "test"})
        with patch.dict(os.environ, {"PLAY_DESKTOP_RUNTIME": str(runtime)}), patch.object(sys, "executable", sys.executable):
            self.bridge.persist_runtime()
            stable = Path(os.environ["UV_PYTHON"])
            import shutil
            shutil.rmtree(runtime)
            self.assertTrue(stable.is_file())
            self.assertIn(self.bridge.root, stable.parents)
            self.assertEqual(sys.executable, str(stable))

    def test_unknown_action_is_closed(self):
        with self.assertRaises(backend.UserError):
            self.bridge.dispatch("run_shell", {"command": "id"})
        self.command.assert_not_called()

    def test_approved_plan_delegates_transaction_and_preserves_rollback_receipt(self):
        for outcome in ("completed", "rolled_back", "action_required"):
            with self.subTest(outcome=outcome):
                payload = self.saved_plan()
                fresh = {"plan_id": "reviewed", "selected_harnesses": ["claude"], "play_version": "0.4.99"}
                fake = SimpleNamespace(build_plan=Mock(return_value=fresh),
                    Progress=self.bridge.bootstrap.Progress, ProgressToken=self.bridge.bootstrap.ProgressToken,
                    apply=Mock(return_value={"status": outcome, "run_id": "mac-" + "b" * 32, "play": {"target_version": "0.4.99"}, "selected_harnesses": ["claude"], "backup": {"id": "backup", "auto_restored": outcome == "rolled_back"}, "steps": [], "report_paths": {"json": str(self.root / "receipt.json")}}),
                    write_report=Mock(return_value=(self.root / "receipt.json", self.root / "receipt.md")))
                with patch.object(self.bridge, "runtime_for_source", return_value=fake), patch.object(self.bridge, "persist_runtime") as runtime:
                    report = self.bridge.install(payload)
                runtime.assert_called_once()
                self.assertEqual(fake.apply.call_args.kwargs["expected_plan_id"], "reviewed")
                self.assertIs(fake.apply.call_args.kwargs["prepared_plan"], fresh)
                self.assertEqual(report["status"], outcome)
                fake.write_report.assert_not_called()
                self.assertFalse((self.bridge.root / "plans" / (payload["planID"] + ".json")).exists())
                self.assertEqual(backend.read_json(self.bridge.root / "active-install.json")["status"], outcome)

    def test_preparation_requires_explicit_action(self):
        with self.assertRaisesRegex(backend.UserError, "approve"):
            self.bridge.prepare({})
        self.command.assert_not_called()

    def test_existing_rote_is_unchanged_when_email_supported(self):
        self.command.return_value.stdout = "rote 0.85.0"
        with patch.object(backend.shutil, "which", return_value="/fake/rote"):
            self.assertEqual(self.bridge.prepare({"approved": True}), {"installed": True})
        self.command.assert_called_once_with(["/fake/rote", "--version"], timeout=10)

    def test_support_report_omits_raw_private_diagnostics(self):
        raw = {"status": "rolled_back", "run_id": "mac-" + "a" * 32,
               "steps": [{"id": "install_play", "status": "failed", "detail": "No such file or directory: /Users/private-person/secret; token=SECRET; user@example.com"}],
               "backup": {"auto_restored": True}}
        public = self.bridge.public_report(raw, self.root / "receipt.json")
        self.assertTrue(public["rolledBack"])
        for secret in ("private-person", "SECRET", "user@example.com"):
            self.assertNotIn(secret, json.dumps(public))
        self.assertEqual(public["issues"][0]["reason"], "A required file or harness folder was missing.")

    def test_existing_receipt_recovers_interrupted_bridge(self):
        identifier = "mac-" + "c" * 32
        report_root = self.root / "receipts"
        receipt = {"run_id": identifier, "status": "rolled_back", "backup": {"auto_restored": True}, "steps": []}
        backend.save_json(report_root / "runs" / f"{identifier}.json", receipt)
        backend.save_json(self.bridge.root / "active-install.json", {"status": "running", "runID": identifier})
        with patch.object(self.bridge.bootstrap, "_report_root", return_value=report_root), patch.object(self.bridge, "identity", return_value={"state": "authenticated"}):
            result = self.bridge.status({})
        self.assertFalse(result["interrupted"])
        self.assertEqual(result["lastReport"]["status"], "rolled_back")

    def test_missing_optional_harness_roots_are_safe_with_lazy_iterators(self):
        def missing(_path):
            yield from ()
            raise FileNotFoundError("optional root does not exist")
        for filename, function in [("install-all", "root_has_rote_provider"), ("play-profile", "iter_rote_skills")]:
            loader = importlib.machinery.SourceFileLoader("mac_test_" + filename.replace("-", "_"), str(ROOT / "scripts/harness" / filename))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            module = importlib.util.module_from_spec(spec)
            sys.modules[loader.name] = module
            loader.exec_module(module)
            with patch.object(Path, "iterdir", missing):
                result = getattr(module, function)(self.root / "missing")
                self.assertFalse(list(result) if filename == "play-profile" else result)


if __name__ == "__main__":
    unittest.main()
