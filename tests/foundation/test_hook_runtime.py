"""Exercise the actual launcher, including imports and subprocess cleanup."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]


class HookRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "scripts/bin"
        self.lib = self.root / "scripts/lib/play"
        self.bin.mkdir(parents=True)
        self.lib.mkdir(parents=True)
        (self.lib / "__init__.py").write_text("")
        shutil.copy2(ROOT / "scripts/bin/play-intercept", self.bin)
        shutil.copy2(ROOT / "scripts/lib/play/hook_runtime.py", self.lib)
        self.worker = self.lib / "intercept.py"
        # A broken/missing environment must never attempt a uv download.
        self.uv_marker = self.root / "uv-was-called"
        uv = self.bin / "uv"
        uv.write_text(f"#!/bin/sh\ntouch '{self.uv_marker}'\nexit 1\n")
        uv.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"}

    def run_hook(self, prompt="Check DNS records"):
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, str(self.bin / "play-intercept"), "prompt"],
            input=json.dumps({"prompt": prompt}),
            text=True, capture_output=True, env=self.env, timeout=5,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        self.assertFalse(self.uv_marker.exists())
        return result.stdout, time.monotonic() - started

    def test_success_preserves_stdin_arguments_and_output(self):
        self.worker.write_text(
            "import json, sys\n"
            "def main(argv):\n"
            "    assert argv == ['prompt']\n"
            "    assert json.load(sys.stdin)['prompt'] == 'Check DNS records'\n"
            "    print(json.dumps({'suppressOutput': True}))\n"
            "    return 0\n"
        )
        output, _ = self.run_hook()
        self.assertEqual({"suppressOutput": True}, json.loads(output))

    def test_real_interceptor_preserves_direct_suggestion(self):
        shutil.copy2(ROOT / "scripts/lib/play/intercept.py", self.worker)
        (self.lib / "search.py").write_text(
            "class SearchError(Exception): pass\n"
            "def search_published(query, *, limit, timeout_seconds):\n"
            "    assert query == 'Check DNS records'\n"
            "    return {'results': [{'relevance_status': 'direct', "
            "'exact_reference': 'team/audit-dns@1.2.3'}], "
            "'source_health': {'mode': 'judged'}}\n"
        )
        output, _ = self.run_hook()
        payload = json.loads(output)
        self.assertTrue(payload["suppressOutput"])
        self.assertEqual("UserPromptSubmit", payload["hookSpecificOutput"]["hookEventName"])
        self.assertIn("team/audit-dns@1.2.3", payload["hookSpecificOutput"]["additionalContext"])

    def test_missing_dependency_is_silent_and_never_installs(self):
        self.worker.write_text("raise ModuleNotFoundError('yaml')\n")
        output, elapsed = self.run_hook()
        self.assertEqual("", output)
        self.assertLess(elapsed, 2)

    def test_discussion_does_not_import_search_dependencies(self):
        shutil.copy2(ROOT / "scripts/lib/play/intercept.py", self.worker)
        (self.lib / "search.py").write_text("import time\ntime.sleep(30)\n")
        output, elapsed = self.run_hook("Should we audit DNS records?")
        self.assertEqual("", output)
        self.assertLess(elapsed, 2)

    def test_slow_import_is_included_in_deadline_and_partial_output_discarded(self):
        self.worker.write_text("import time\nprint('partial output', flush=True)\ntime.sleep(30)\n")
        output, elapsed = self.run_hook()
        self.assertEqual("", output)
        self.assertLess(elapsed, 4.5)

    def test_deadline_covers_combined_steps_and_kills_descendants(self):
        marker = self.root / "descendant-survived"
        child = f"import time; from pathlib import Path; time.sleep(3.6); Path({str(marker)!r}).touch()"
        self.worker.write_text(
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
            "time.sleep(1.7)\n"  # Identity check consumes part of the budget.
            "time.sleep(1.7)\n"  # Search must not get a fresh budget.
            "def main(argv):\n"
            "    print('too late')\n"
            "    return 0\n"
        )
        output, elapsed = self.run_hook()
        self.assertEqual("", output)
        self.assertLess(elapsed, 4.5)
        time.sleep(1)
        self.assertFalse(marker.exists(), "timed-out hook left a child running")

    def test_uses_existing_environment_without_uv(self):
        python = self.root / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\nprintf 'existing environment'\n")
        python.chmod(0o755)
        output, _ = self.run_hook()
        self.assertEqual("existing environment", output)


if __name__ == "__main__":
    unittest.main()
