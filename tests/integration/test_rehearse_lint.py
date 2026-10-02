from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.lib.play.audit import rehearse
from scripts.lib.play.audit.package import load

MAIN_TS = """/**
 * @rote-frontmatter
 * ---
 * name: echo
 * description: compat probe echo
 * metadata:
 *   rote_version: "0.1.0"
 *   flow_type: sequential
 *   requires_sessions: false
 * parameters:
 * - name: who
 *   param_type: string
 *   required: true
 *   default: null
 *   description: who
 *   example: null
 *   valid_values: null
 * steps:
 *   show:
 *     type: process.exec
 *     argv:
 *     - sh
 *     - -c
 *     - 'printf "who=%s" "$0"'
 *     - '$who'
 * ---
 */
"""

DEPS_TOML = 'schema_version = 1\n\n[[tools]]\nid = "sh"\ncommand = "sh"\nrequired = true\n'

STRIPPED = ("CLAUDECODE", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "XDG_CONFIG_HOME", "ROTE_OUTPUT_MODE")


@unittest.skipUnless(shutil.which("rote"), "rote is not on PATH")
class RehearseLintTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        self.flows = home / ".rote" / "flows"
        environment = {key: value for key, value in os.environ.items() if key not in STRIPPED}
        environment.update(
            HOME=str(home),
            ROTE_HOME=str(home / ".rote"),
            ROTE_NO_AUTO_UPDATE="1",
            ROTE_TELEMETRY_DISABLED="1",
            ROTE_NO_HINTS="1",
        )
        patcher = patch.dict(os.environ, environment, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _seed(self, root: Path) -> Path:
        root.mkdir(parents=True)
        (root / "main.ts").write_text(MAIN_TS)
        (root / "deps.toml").write_text(DEPS_TOML)
        return root

    def test_development_copy_is_linted(self) -> None:
        root = self._seed(self.flows / "acme" / "echo")

        result = rehearse._lint(load(root))

        self.assertTrue(result["ran"], result)
        self.assertTrue(result["static_checks_passed"], result)

    def test_unresolvable_package_reports_rote_error(self) -> None:
        root = self._seed(self.flows.parent / "elsewhere" / "acme" / "missing")

        result = rehearse._lint(load(root))

        self.assertFalse(result["ran"], result)
        self.assertIn("not found", result["reason"])


if __name__ == "__main__":
    unittest.main()
