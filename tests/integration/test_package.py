from __future__ import annotations

import unittest
from pathlib import Path

from scripts.lib.play.package import ROOT, TARGET, differences, materialize


class PluginPackageTest(unittest.TestCase):
    def test_payload_contains_runtime_and_just_configuration(self) -> None:
        self.assertTrue((TARGET / "SKILL.md").is_file())
        self.assertTrue((TARGET / "justfile").is_file())
        self.assertTrue((TARGET / "scripts/harness/play-profile").is_file())
        self.assertTrue((TARGET / "scripts/harness/start-harness").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-preflight").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-presentation").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-publication").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-publication-gate").is_file())
        self.assertTrue((TARGET / "ui/thinking-orbs/package-lock.json").is_file())
        self.assertTrue((TARGET / "ui/thinking-orbs/src/PlayActivity.tsx").is_file())
        self.assertTrue((TARGET / "ui/thinking-orbs/src/PlayThinkingOrb.tsx").is_file())

    def test_payload_matches_source(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            expected = Path(temporary) / "play"
            materialize(expected)
            self.assertEqual([], differences(expected, TARGET))

    def test_packager_is_not_recursively_installed(self) -> None:
        self.assertFalse((TARGET / "scripts/bin/package-plugin").exists())
        self.assertFalse((TARGET / "scripts/lib/play/package.py").exists())
        self.assertTrue((ROOT / "scripts/bin/package-plugin").is_file())


if __name__ == "__main__":
    unittest.main()
