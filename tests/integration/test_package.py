from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.lib.play.package import ROOT, TARGET, differences, materialize


class PluginPackageTest(unittest.TestCase):
    def test_payload_contains_runtime_and_just_configuration(self) -> None:
        self.assertTrue((TARGET / "SKILL.md").is_file())
        self.assertTrue((TARGET / "VERSION").is_file())
        self.assertTrue((TARGET / "install.sh").is_file())
        self.assertTrue((TARGET / "justfile").is_file())
        self.assertTrue((TARGET / "scripts/harness/install-all").is_file())
        self.assertTrue((TARGET / "scripts/harness/play-profile").is_file())
        self.assertTrue((TARGET / "scripts/harness/start-harness").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-activate").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-activate").stat().st_mode & 0o111)
        self.assertTrue((TARGET / "scripts/bin/play-cheat-sheet").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-cheat-sheet").stat().st_mode & 0o111)
        self.assertTrue((TARGET / "scripts/bin/play-preflight").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-onboarding").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-presentation").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-publication").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-publication-gate").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-public-owner").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-routing").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-routing").stat().st_mode & 0o111)
        self.assertTrue((TARGET / "scripts/bin/play-certificate").is_file())
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

    def test_plugin_versions_match_the_packaged_version(self) -> None:
        expected = (ROOT / "VERSION").read_text().strip()
        manifests = (
            ROOT / "plugins/play/package.json",
            ROOT / "plugins/play/.codex-plugin/plugin.json",
            ROOT / "plugins/play/.claude-plugin/plugin.json",
            ROOT / "plugins/play/.kimi-plugin/plugin.json",
            ROOT / "plugins/play/.cursor-plugin/plugin.json",
        )
        self.assertEqual(expected, (TARGET / "VERSION").read_text().strip())
        for manifest in manifests:
            self.assertEqual(expected, json.loads(manifest.read_text())["version"])

    def test_claude_plugin_uses_bootstrap_for_rote_convergence(self) -> None:
        manifest = json.loads(
            (ROOT / "plugins/play/.claude-plugin/plugin.json").read_text()
        )

        self.assertNotIn("dependencies", manifest)

    def test_marketplace_session_hook_never_reinstalls_activation(self) -> None:
        hooks = json.loads((ROOT / "plugins/play/hooks/hooks.json").read_text())
        command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]

        self.assertIn("${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-}}", command)
        self.assertIn("play-inbox", command)
        self.assertNotIn("play-activate", command)
        self.assertNotIn("Play activation incomplete", command)

    def test_active_sources_have_no_legacy_flow_commands(self) -> None:
        files = [ROOT / "README.md", ROOT / "SKILL.md"]
        for directory in (ROOT / "references", ROOT / "scripts", TARGET):
            files.extend(path for path in directory.rglob("*") if path.is_file())
        legacy_patterns = (
            "rote flow",
            "rote registry flow",
            '"rote", "flow"',
            '"registry", "flow"',
        )
        matches = []
        for path in files:
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            for pattern in legacy_patterns:
                if pattern in text:
                    matches.append(f"{path.relative_to(ROOT)}: {pattern}")
        self.assertEqual([], matches)


if __name__ == "__main__":
    unittest.main()
