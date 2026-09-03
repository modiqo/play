from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.audit import adapters, card, fetch, frontmatter, host, rules, store  # noqa: E402
from play.audit.cli import audit_target, main, resolve_target  # noqa: E402
from play.audit.runner import safe_audit  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "audit"
JUDGMENT_IDS = {rule.id for rule in rules.RULES.values() if rule.cls == "judgment"}
FACT_IDS = {rule.id for rule in rules.RULES.values() if rule.cls == "fact"}


def audit(name: str, **kwargs):
    kwargs.setdefault("read_adapters", False)
    kwargs.setdefault("persist", False)
    return safe_audit(FIXTURES / name, reference=f"audit/{name}", **kwargs)


def ids(envelope, section: str) -> set[str]:
    return {item["id"] for item in envelope[section]}


class NoProbe(unittest.TestCase):
    """Host probes spawn `--version`; tests never do."""

    def setUp(self) -> None:
        self._environ = patch.dict(os.environ, {"PLAY_AUDIT_NO_PROBE": "1"})
        self._environ.start()

    def tearDown(self) -> None:
        self._environ.stop()


class RuleRegistryTest(unittest.TestCase):
    def test_every_rule_has_a_class_owner_and_fix(self) -> None:
        for rule in rules.RULES.values():
            self.assertIn(rule.cls, {"fact", "judgment"}, rule.id)
            self.assertTrue(rule.owner.startswith("rote-"), rule.id)
            self.assertTrue(rule.fix, rule.id)
            self.assertTrue(rule.message, rule.id)


class FrontmatterTest(unittest.TestCase):
    def test_extracts_yaml_from_jsdoc(self) -> None:
        front = frontmatter.extract((FIXTURES / "clean" / "main.ts").read_text())
        self.assertIsNone(front.error)
        self.assertEqual(["repo"], front.parameter_names)
        self.assertTrue(front.parameters_top_level)
        self.assertEqual("steps_with_presentation", front.execution_model)
        self.assertIn("count", front.steps)
        self.assertIn("new FlowOutput", front.body)

    def test_missing_block_is_an_error_not_a_guess(self) -> None:
        front = frontmatter.extract("const x = 1;\n")
        self.assertEqual("no @rote-frontmatter block", front.error)
        self.assertEqual({}, front.data)

    def test_usage_notes_after_the_closing_marker_are_ignored(self) -> None:
        source = (
            "/**\n * @rote-frontmatter\n * ---\n * name: noted\n * description: d\n"
            " * metadata:\n *   version: 1.0.0\n * parameters: []\n * steps: {}\n * ---\n *\n"
            " * Usage:\n *   rote play run ~/.rote/flows/noted/main.ts key=value\n */\nconst x = 1;\n"
        )
        front = frontmatter.extract(source)
        self.assertIsNone(front.error)
        self.assertEqual("noted", front.data["name"])
        self.assertIn("const x = 1", front.body)

    def test_fence_and_close_on_one_line_marker_on_opener_and_dex_alias(self) -> None:
        # The shapes rote 0.77 emitted: marker on the `/**` line, `* --- */` closing.
        source = (
            "#!/usr/bin/env -S rote play run\n/** @rote-frontmatter\n * ---\n * name: ci\n"
            " * description: d\n * parameters: []\n * metadata:\n *   version: 0.1.0\n"
            " * steps:\n *   investigate:\n *     type: process.exec\n *     argv: [python3, x.py]\n"
            " * --- */\nconst sdk = await import(\"__ROTE_PRESENTATION_SDK__\");\n"
        )
        front = frontmatter.extract(source)
        self.assertIsNone(front.error, front.error)
        self.assertEqual("ci", front.data["name"])
        self.assertIn("investigate", front.steps)
        self.assertIn("const sdk", front.body)
        dex = frontmatter.extract(source.replace("@rote-frontmatter", "@dex-frontmatter"))
        self.assertIsNone(dex.error)

    def test_marker_outside_a_jsdoc_block_is_ignored(self) -> None:
        front = frontmatter.extract("// @rote-frontmatter\n// ---\n// name: x\n// ---\n")
        self.assertEqual("no @rote-frontmatter block", front.error)

    def test_a_dash_fence_inside_block_scalar_content_does_not_close_the_yaml(self) -> None:
        source = (
            "/**\n * @rote-frontmatter\n * ---\n * name: s\n * description: |\n *   line one\n *     ---\n"
            " *   line two\n * metadata:\n *   version: 1.0.0\n * steps: {}\n * ---\n */\n"
        )
        front = frontmatter.extract(source)
        self.assertIsNone(front.error, front.error)
        self.assertEqual("s", front.data["name"])
        self.assertIn("---", front.data["description"])

    def test_nested_parameters_and_suppressions(self) -> None:
        front = frontmatter.extract((FIXTURES / "nested-params" / "main.ts").read_text())
        self.assertFalse(front.parameters_top_level)
        self.assertEqual(["name"], front.parameter_names)
        self.assertEqual({"PARAMETERS_UNDER_METADATA": "generated by an older rote; works by fallback"}, front.suppressions)


class FixtureFindingsTest(NoProbe):
    def test_clean_play_has_nothing_to_say(self) -> None:
        envelope = audit("clean")
        self.assertEqual("ok", envelope["status"])
        self.assertEqual([], envelope["facts"])
        self.assertEqual([], envelope["judgments"])
        self.assertEqual([], envelope["unknowns"])
        self.assertIn("git", envelope["reach"]["commands"], "shell resource commands count as reach")

    def test_partial_scan(self) -> None:
        envelope = audit("partial-scan")
        self.assertEqual({"FANOUT_OVER_PREVIEW", "STEP_NO_TIMEOUT"}, ids(envelope, "facts"))
        timeout = next(f for f in envelope["facts"] if f["id"] == "STEP_NO_TIMEOUT")
        self.assertEqual("find", timeout["evidence"]["step"])
        self.assertEqual({"UNRELIABLE_EXIT_STATUS", "TOOL_DECLARED_UNUSED"}, ids(envelope, "judgments"))
        unused = next(item for item in envelope["judgments"] if item["id"] == "TOOL_DECLARED_UNUSED")
        self.assertEqual("rsync", unused["evidence"]["command"])
        self.assertEqual("rote-troubleshooting", next(f for f in envelope["facts"] if f["id"] == "FANOUT_OVER_PREVIEW")["owner"])

    def test_stranded_body(self) -> None:
        envelope = audit("stranded")
        self.assertEqual({"BODY_STRANDED", "DEPS_TOML_MISSING", "PARAMETERS_UNDER_METADATA", "STEP_NO_TIMEOUT"}, ids(envelope, "facts"))
        self.assertEqual({"PARAM_UNREFERENCED"}, ids(envelope, "judgments"))
        self.assertEqual([("INLINE_BODY_UNREAD", "steps.scan")], [(u["kind"], u["subject"]) for u in envelope["unknowns"]])
        self.assertEqual(["scan"], envelope["reach"]["unread_bodies"])

    def test_python_floor(self) -> None:
        envelope = audit("pyfloor")
        facts = envelope["facts"]
        self.assertEqual({"INTERPRETER_FLOOR_MISSING", "PY_FLOOR_TOO_LOW"}, ids(envelope, "facts"))
        needs = sorted((f["evidence"]["construct"], f["evidence"]["needs"]) for f in facts if f["id"] == "PY_FLOOR_TOO_LOW")
        self.assertEqual([("a PEP 604 union in an evaluated annotation", "3.10"), ("an unguarded `import tomllib`", "3.11")], needs)
        self.assertEqual([], envelope["judgments"])

    def test_runtime_pipe_expressions_are_not_unions_even_without_future_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "pipes"
            (root / "resources").mkdir(parents=True)
            (root / "main.ts").write_text((FIXTURES / "pyfloor" / "main.ts").read_text())
            (root / "deps.toml").write_text((FIXTURES / "pyfloor" / "deps.toml").read_text())
            (root / "resources" / "check.py").write_text(
                "import os\nmode = os.O_RDONLY | os.O_NONBLOCK\nmerged = {'a': 1} | {'b': 2}\n"
                "flags = 0\nflags |= 4\nnames = {'x'} | {'y'}\n")
            envelope = safe_audit(root, reference="audit/pipes", read_adapters=False, persist=False)
        self.assertNotIn("PY_FLOOR_TOO_LOW", ids(envelope, "facts"))

    def test_python_floor_negative_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "neg"
            (root / "resources").mkdir(parents=True)
            (root / "main.ts").write_text((FIXTURES / "pyfloor" / "main.ts").read_text())
            (root / "deps.toml").write_text(
                'schema_version = 1\n\n[[tools]]\nid = "python3"\ncommand = "python3"\nrequired = true\nversion_requirement = ">=3.11.0"\n')
            (root / "resources" / "check.py").write_text(
                "from __future__ import annotations\n"
                "import sys, os\n"
                "try:\n    import tomllib\nexcept ImportError:\n    tomllib = None\n"
                "x = a | b\n"
                "mode = os.O_RDONLY | os.O_NONBLOCK\n"
                "merged = {'a': 1} | {'b': 2}\n"
                "names = {'x'} | {'y'}\n"
                "def f(v: int | None) -> str | None:\n    return None\n")
            envelope = safe_audit(root, reference="audit/neg", read_adapters=False, persist=False)
        self.assertNotIn("PY_FLOOR_TOO_LOW", ids(envelope, "facts"))
        self.assertNotIn("INTERPRETER_FLOOR_MISSING", ids(envelope, "facts"))

    def test_missing_resource_and_home_path(self) -> None:
        envelope = audit("missing-resource")
        self.assertEqual({"ABSOLUTE_HOME_PATH", "DEPENDS_ON_UNKNOWN", "RESOURCE_MISSING"}, ids(envelope, "facts"))

    def test_spawned_commands(self) -> None:
        envelope = audit("spawns")
        self.assertEqual({"DENO_COMMAND_UNDECLARED", "SUBPROCESS_UNDECLARED"}, ids(envelope, "facts"))
        self.assertEqual({"DYNAMIC_COMMAND_UNRESOLVABLE"}, ids(envelope, "judgments"))
        commands = {f["evidence"]["command"] for f in envelope["facts"]}
        self.assertEqual({"gh", "docker"}, commands, "python3 is declared and must not be flagged")
        self.assertTrue(all("line" in f["location"] for f in envelope["facts"]))

    def test_suppression_moves_a_fact_out_of_facts(self) -> None:
        envelope = audit("nested-params")
        self.assertEqual([], envelope["facts"])
        self.assertEqual(["PARAMETERS_UNDER_METADATA"], [s["id"] for s in envelope["suppressions"]])
        self.assertEqual(1, envelope["summary"]["suppressed"])


class HostPathTest(NoProbe):
    def test_saved_consumer_path_wins_over_the_venv_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "bin"
            fake.mkdir()
            (fake / "python3").write_text("#!/bin/sh\n")
            (fake / "python3").chmod(0o755)
            with patch.dict(os.environ, {"PLAY_AUDIT_HOST_PATH": str(fake)}):
                envelope = audit("pyfloor")
        need = next(n for n in envelope["host"]["needs"] if n["name"] == "python3")
        self.assertEqual(str(fake / "python3"), need["path"])


class PerCommandFindingsTest(NoProbe):
    def test_interpreter_floor_is_one_finding_per_tool_naming_every_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "multi"
            root.mkdir()
            steps = "".join(
                f" *   s{i}:\n *     type: process.exec\n *     argv: [python3, -c, 'print({i})']\n *     timeout_ms: 1000\n"
                for i in range(3)
            )
            (root / "main.ts").write_text(
                "/**\n * @rote-frontmatter\n * ---\n * name: multi\n * description: m\n * metadata:\n"
                " *   version: 1.0.0\n *   execution_model: steps_with_presentation\n * parameters: []\n"
                f" * steps:\n{steps} * ---\n */\nconst x = 1;\n")
            (root / "deps.toml").write_text('schema_version = 1\n\n[[tools]]\nid = "python3"\ncommand = "python3"\nrequired = true\n')
            envelope = safe_audit(root, reference="audit/multi", read_adapters=False, persist=False)
        floors = [f for f in envelope["facts"] if f["id"] == "INTERPRETER_FLOOR_MISSING"]
        self.assertEqual(1, len(floors))
        self.assertEqual("s0, s1, s2", floors[0]["evidence"]["step"])
        self.assertEqual({"file": "deps.toml"}, floors[0]["location"])


class ReachFromInlineCodeTest(NoProbe):
    def _play(self, temp: str, argv_yaml: str, deps: str, body: str = "const x = 1;\n") -> Path:
        root = Path(temp) / "inline"
        root.mkdir()
        (root / "main.ts").write_text(
            "/**\n * @rote-frontmatter\n * ---\n * name: inline\n * description: i\n * metadata:\n"
            " *   version: 1.0.0\n *   execution_model: steps_with_presentation\n * parameters:\n"
            " * - name: repo\n *   type: string\n *   required: true\n * steps:\n *   go:\n"
            " *     type: process.exec\n" + argv_yaml + " *     timeout_ms: 1000\n * ---\n */\n" + body)
        (root / "deps.toml").write_text(deps)
        return root

    def test_tool_used_inside_inline_shell_is_not_unused(self) -> None:
        deps = 'schema_version = 1\n\n[[tools]]\nid = "sh"\ncommand = "sh"\nrequired = true\n\n[[tools]]\nid = "wc"\ncommand = "wc"\nrequired = true\n'
        with tempfile.TemporaryDirectory() as temp:
            root = self._play(temp, " *     argv: [sh, -c, 'ls ${repo} | wc -l']\n", deps)
            envelope = safe_audit(root, reference="audit/inline", read_adapters=False, persist=False)
        self.assertNotIn("TOOL_DECLARED_UNUSED", ids(envelope, "judgments"))
        self.assertNotIn("PARAM_UNREFERENCED", ids(envelope, "judgments"), "${repo} is a parameter read")
        self.assertIn("wc", envelope["reach"]["commands"])

    def test_unused_tool_is_not_claimed_when_a_spawn_is_dynamic(self) -> None:
        deps = 'schema_version = 1\n\n[[tools]]\nid = "python3"\ncommand = "python3"\nrequired = true\nversion_requirement = ">=3.10"\n\n[[tools]]\nid = "git"\ncommand = "git"\nrequired = true\n'
        with tempfile.TemporaryDirectory() as temp:
            root = self._play(temp, " *     argv: [python3, '@resource{run.py}', $repo]\n", deps)
            (root / "resources").mkdir()
            (root / "resources" / "run.py").write_text("import subprocess, sys\ncmd = sys.argv[1:]\nsubprocess.run(cmd)\n")
            envelope = safe_audit(root, reference="audit/inline", read_adapters=False, persist=False)
        self.assertNotIn("TOOL_DECLARED_UNUSED", ids(envelope, "judgments"))
        self.assertIn("DYNAMIC_COMMAND_UNRESOLVABLE", ids(envelope, "judgments"))

    def test_shipped_tests_are_not_the_plays_reach(self) -> None:
        deps = 'schema_version = 1\n\n[[tools]]\nid = "python3"\ncommand = "python3"\nrequired = true\nversion_requirement = ">=3.10"\n'
        with tempfile.TemporaryDirectory() as temp:
            root = self._play(temp, " *     argv: [python3, '@resource{run.py}', $repo]\n", deps)
            (root / "resources" / "tests").mkdir(parents=True)
            (root / "resources" / "run.py").write_text("print('ok')\n")
            (root / "resources" / "tests" / "test_run.py").write_text("import subprocess\nsubprocess.run(['rote', 'play', 'run', 'x'])\ndef f(v: int | None): pass\n")
            envelope = safe_audit(root, reference="audit/inline", read_adapters=False, persist=False)
        self.assertNotIn("SUBPROCESS_UNDECLARED", ids(envelope, "facts"))
        self.assertNotIn("PY_FLOOR_TOO_LOW", ids(envelope, "facts"))


class ConsumerCardTest(NoProbe):
    def test_card_never_shows_judgments_rule_ids_or_counts(self) -> None:
        for name in ("partial-scan", "stranded", "spawns", "pyfloor"):
            envelope = audit(name)
            text = card(envelope)
            for rule_id in JUDGMENT_IDS | FACT_IDS:
                self.assertNotIn(rule_id, text, f"{rule_id} leaked into the card for {name}")
            self.assertNotIn("judgment", text.lower())
            self.assertNotIn("fact", text.lower().replace("artifacts", ""))
            self.assertIn("Can it run here", text)

    def test_card_states_unread_bodies(self) -> None:
        text = card(audit("stranded"))
        self.assertIn("runs code this inspection could not read", text)

    def test_card_is_empty_when_audit_unavailable(self) -> None:
        envelope = safe_audit(Path("/nonexistent/play"), reference="x/y", read_adapters=False, persist=False)
        self.assertEqual("ok", envelope["status"], "a missing main.ts is an unknown, not a crash")
        from play.audit.runner import unavailable
        self.assertEqual("", card(unavailable("x/y", "boom")))


class FailSafeTest(NoProbe):
    def test_every_extractor_raising_still_yields_an_envelope(self) -> None:
        boom = patch("play.audit.steps.analyze", side_effect=RuntimeError("steps exploded"))
        boom2 = patch("play.audit.bodies.analyze", side_effect=RuntimeError("bodies exploded"))
        boom3 = patch("play.audit.host.resolve", side_effect=RuntimeError("host exploded"))
        with boom, boom2, boom3:
            envelope = audit("clean")
        self.assertEqual("ok", envelope["status"])
        kinds = {(u["kind"], u["subject"]) for u in envelope["unknowns"]}
        self.assertIn(("EXTRACTOR_FAILED", "steps"), kinds)
        self.assertIn(("EXTRACTOR_FAILED", "bodies"), kinds)
        self.assertIn(("EXTRACTOR_FAILED", "host"), kinds)
        self.assertEqual([], envelope["facts"])
        self.assertTrue(envelope["summary"]["can_run_here"])

    def test_package_load_failure_is_audit_unavailable(self) -> None:
        with patch("play.audit.package.load", side_effect=OSError("disk gone")):
            envelope = audit("clean")
        self.assertEqual("audit_unavailable", envelope["status"])
        self.assertIn("disk gone", envelope["reason"])
        self.assertEqual("", card(envelope))

    def test_extractor_timeout_is_an_unknown(self) -> None:
        import time as _time

        def slow(package):
            _time.sleep(5)

        with patch("play.audit.bodies.analyze", side_effect=slow), patch("play.audit.runner._TASK_TIMEOUT_SECONDS", 0.2):
            envelope = audit("clean")
        self.assertEqual("ok", envelope["status"])
        self.assertTrue(any(u["subject"] == "bodies" and "timed out" in u["reason"] for u in envelope["unknowns"]))


class HostProfileTest(NoProbe):
    def test_stock_macos_rejects_a_declared_floor_above_3_9(self) -> None:
        envelope = audit("spawns", profile="stock-macos")
        need = next(n for n in envelope["host"]["needs"] if n["name"] == "python3")
        self.assertEqual("version_low", need["status"])
        self.assertFalse(envelope["summary"]["can_run_here"])
        self.assertIn("3.9.6", envelope["summary"]["cannot_run_reason"])

    def test_ubuntu_profile_accepts_it(self) -> None:
        envelope = audit("spawns", profile="ubuntu-lts")
        self.assertTrue(envelope["summary"]["can_run_here"])

    def test_requirement_parsing(self) -> None:
        self.assertTrue(host.satisfies("Python 3.12.3", ">=3.10.0"))
        self.assertFalse(host.satisfies("3.9.6", ">=3.10"))
        self.assertIsNone(host.satisfies(None, ">=3.10"))
        self.assertIsNone(host.satisfies("3.9.6", None))


class AdapterCorrelationTest(NoProbe):
    def test_operation_and_provenance_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "weather"
            root.mkdir()
            (root / "main.ts").write_text(
                "/**\n * @rote-frontmatter\n * ---\n * name: weather\n * description: w\n"
                " * metadata:\n *   version: 1.0.0\n *   execution_model: steps_with_presentation\n"
                " * requires_endpoints:\n *   - adapter/open-meteo\n"
                " * adapter_sources:\n *   adapter/open-meteo: robpumpaf/open-meteo\n"
                " * parameters: []\n * steps:\n *   forecast:\n *     endpoint: adapter/open-meteo\n"
                " *     method: get_v2_forecast\n *     timeout_ms: 5000\n * ---\n */\n"
                "const sdk = await import('__ROTE_PRESENTATION_SDK__');\n")

            def reader(adapter_id: str) -> adapters.AdapterInfo:
                return adapters.AdapterInfo(adapter_id, operations={"get_v1_forecast"}, provenance="debasishg/open-meteo", fingerprint="mcp_x")

            envelope = safe_audit(root, reference="audit/weather", adapter_reader=reader, persist=False)
        self.assertEqual({"ADAPTER_OPERATION_UNKNOWN", "ADAPTER_SOURCE_PROVENANCE_DIFFERS"}, ids(envelope, "facts"))
        self.assertEqual(["adapter/open-meteo"], envelope["reach"]["services"])

    def test_unreadable_adapter_is_an_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "svc"
            root.mkdir()
            (root / "main.ts").write_text(
                "/**\n * @rote-frontmatter\n * ---\n * name: svc\n * description: s\n * metadata:\n *   version: 1.0.0\n"
                " * requires_endpoints:\n *   - adapter/ghost\n * parameters: []\n * steps: {}\n * ---\n */\n")

            def reader(adapter_id: str) -> adapters.AdapterInfo:
                return adapters.AdapterInfo(adapter_id, error="rote adapter info ghost: not installed")

            envelope = safe_audit(root, reference="audit/svc", adapter_reader=reader, persist=False)
        self.assertEqual([("ADAPTER_NOT_READABLE", "adapter/ghost")], [(u["kind"], u["subject"]) for u in envelope["unknowns"]])
        self.assertEqual([], envelope["facts"])


class StoreTest(NoProbe):
    def test_persist_history_load_and_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"PLAY_HOME": temp}):
            first = audit("partial-scan", persist=True)
            self.assertIsNotNone(first["history_ref"])
            self.assertTrue(Path(first["history_ref"]).is_file())
            loaded = store.load("audit/partial-scan")
            assert loaded is not None
            self.assertEqual(first["subject"]["digest"], loaded["subject"]["digest"])
            by_digest = store.load("audit/partial-scan", digest=first["subject"]["digest"])
            self.assertIsNotNone(by_digest)
            entries = store.history("audit/partial-scan")
            self.assertEqual(["audit"], [e["event"] for e in entries])
            self.assertEqual(2, entries[0]["open_facts"])
            fixed = audit("clean", persist=False)
            delta = store.delta(first, fixed)
            self.assertEqual(4, len(delta["closed"]))
            self.assertEqual([], delta["new"])
            self.assertEqual(first["subject"]["digest"], delta["digest_before"])

    def test_store_failure_is_an_unknown_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"PLAY_HOME": str(Path(temp) / "file")}):
            (Path(temp) / "file").write_text("not a directory")
            envelope = audit("clean", persist=True)
        self.assertEqual("ok", envelope["status"])
        self.assertTrue(any(u["kind"] == "STORE_FAILED" for u in envelope["unknowns"]))


class CliTest(NoProbe):
    def _run(self, *argv: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(list(argv))
        return code, buffer.getvalue()

    def test_default_is_the_card_and_exit_is_always_zero(self) -> None:
        code, out = self._run(str(FIXTURES / "partial-scan"), "--no-adapters", "--no-store")
        self.assertEqual(0, code)
        self.assertIn("What it does, in order", out)
        self.assertNotIn("UNRELIABLE_EXIT_STATUS", out)

    def test_author_and_json_modes(self) -> None:
        code, out = self._run(str(FIXTURES / "stranded"), "--author", "--no-adapters", "--no-store")
        self.assertEqual(0, code)
        self.assertIn("BODY_STRANDED", out)
        self.assertIn("owner rote-flow-authoring", out)
        self.assertIn("Next", out)
        code, out = self._run(str(FIXTURES / "stranded"), "--json", "--no-adapters", "--no-store")
        self.assertEqual("play-audit/1", json.loads(out)["schema"])

    def test_unresolvable_reference_is_unavailable_not_a_crash(self) -> None:
        with patch.dict(os.environ, {"ROTE_HOME": tempfile.mkdtemp()}), \
                patch("play.audit.fetch.pull", return_value=(None, "could not pull nobody/nothing: Flow not found")):
            code, out = self._run("nobody/nothing@1.0.0", "--json", "--no-store")
        self.assertEqual(0, code)
        self.assertEqual("audit_unavailable", json.loads(out)["status"])

    def test_history_and_show(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"PLAY_HOME": temp}):
            self._run(str(FIXTURES / "pyfloor"), "--no-adapters")
            code, out = self._run("history", "audit/pyfloor")
            self.assertEqual(0, code)
            self.assertIn("facts 3", out)
            code, out = self._run("show", "audit/pyfloor", "--author")
            self.assertIn("PY_FLOOR_TOO_LOW", out)
            code, out = self._run("history", "audit/never")
            self.assertIn("no audits recorded", out)

    def test_resolve_target_forms(self) -> None:
        root, reference = resolve_target(str(FIXTURES / "clean" / "main.ts"))
        self.assertEqual(FIXTURES / "clean", root)
        self.assertEqual("audit/clean", reference)
        with patch.dict(os.environ, {"ROTE_HOME": tempfile.mkdtemp()}):
            root, reference = resolve_target("https://play.modiqo.ai/owner/name@0.1.0")
        self.assertIsNone(root)
        self.assertEqual("owner/name", reference)


if __name__ == "__main__":
    unittest.main()


class PullTest(NoProbe):
    def test_pull_lands_in_a_temporary_home_that_borrows_the_real_login(self) -> None:
        with tempfile.TemporaryDirectory() as real:
            (Path(real) / "config").mkdir()
            (Path(real) / "flows" / "x").mkdir(parents=True)
            with patch.dict(os.environ, {"ROTE_HOME": real}), patch("play.audit.fetch.shutil.which", return_value="/usr/bin/rote"):
                seen: dict[str, Any] = {}

                def runner(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
                    seen["argv"] = argv
                    home = Path(env["ROTE_HOME"])
                    seen["links"] = sorted(p.name for p in home.iterdir())
                    target = home / "flows" / "owner" / "name"
                    target.mkdir(parents=True)
                    (target / "main.ts").write_text((FIXTURES / "clean" / "main.ts").read_text())
                    return 0, "ok", ""

                pulled, error = fetch.pull("owner", "name", runner=runner)
                self.assertIsNone(error)
                assert pulled is not None
                self.assertEqual(["rote", "registry", "play", "pull", "owner/name", "--yes", "--no-deps"], seen["argv"])
                self.assertIn("config", seen["links"], "login and caches are shared")
                self.assertEqual(["config", "flows"], seen["links"], "the real flows store is never linked")
                self.assertTrue((pulled.root / "main.ts").is_file())
                pulled.cleanup()
                self.assertFalse(pulled.temp_home.exists())

    def test_pull_failure_is_reported_and_leaves_nothing_behind(self) -> None:
        with patch("play.audit.fetch.shutil.which", return_value="/usr/bin/rote"):
            pulled, error = fetch.pull("nobody", "nothing", runner=lambda argv, env: (1, "", "error: Flow not found: nobody/nothing"))
        self.assertIsNone(pulled)
        self.assertIn("Flow not found", str(error))

    def test_audit_target_pulls_when_not_installed(self) -> None:
        def fake_pull(owner: str, name: str, *, runner=None):
            home = Path(tempfile.mkdtemp())
            root = home / "flows" / owner / name
            root.mkdir(parents=True)
            for item in (FIXTURES / "partial-scan").iterdir():
                (root / item.name).write_text(item.read_text())
            return fetch.Pulled(root=root, temp_home=home, owner=owner, name=name), None

        with patch.dict(os.environ, {"ROTE_HOME": tempfile.mkdtemp()}), patch("play.audit.fetch.pull", side_effect=fake_pull):
            envelope = audit_target("https://play.modiqo.ai/owner/scan@0.0.9", read_adapters=False, persist=False)
        self.assertEqual("ok", envelope["status"])
        self.assertEqual("pulled", envelope["subject"]["source"])
        self.assertEqual("owner/scan", envelope["subject"]["reference"])
        self.assertIn("FANOUT_OVER_PREVIEW", {f["id"] for f in envelope["facts"]})
        self.assertTrue(any(u["kind"] == "VERSION_DIFFERS" for u in envelope["unknowns"]), "requested 0.0.9, pulled 0.1.0")
        self.assertFalse(Path(envelope["subject"]["path"]).exists(), "temporary pull is cleaned up")

    def test_no_pull_keeps_the_old_behaviour(self) -> None:
        with patch.dict(os.environ, {"ROTE_HOME": tempfile.mkdtemp()}):
            envelope = audit_target("owner/name", pull=False, persist=False)
        self.assertEqual("audit_unavailable", envelope["status"])
        self.assertIn("pull it first", envelope["reason"])
