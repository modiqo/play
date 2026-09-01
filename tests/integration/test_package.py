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
        self.assertTrue((TARGET / "scripts/lib/play/harnesses.py").is_file())
        self.assertTrue((TARGET / "scripts/lib/play/identity.py").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-activate").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-activate").stat().st_mode & 0o111)
        self.assertTrue((TARGET / "scripts/bin/play").is_file())
        self.assertTrue((TARGET / "scripts/bin/play").stat().st_mode & 0o111)
        self.assertTrue((TARGET / "scripts/bin/play-cheat-sheet").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-cheat-sheet").stat().st_mode & 0o111)
        self.assertTrue((TARGET / "scripts/bin/play-guide").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-guide").stat().st_mode & 0o111)
        self.assertTrue((TARGET / "scripts/bin/play-journal").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-journal").stat().st_mode & 0o111)
        self.assertTrue((TARGET / "scripts/bin/play-journey").is_file())
        self.assertTrue((TARGET / "scripts/bin/play-journey").stat().st_mode & 0o111)
        self.assertTrue((TARGET / "references/explore/journey-graph.schema.json").is_file())
        self.assertTrue((TARGET / "references/explore/journey-viewport.schema.json").is_file())
        self.assertTrue((TARGET / "references/explore/journey-scene.schema.json").is_file())
        self.assertTrue((TARGET / "references/explore/journey-story.schema.json").is_file())
        self.assertTrue((TARGET / "scripts/lib/play/journey_viewer/index.html").is_file())
        self.assertTrue((TARGET / "scripts/lib/play/journey_viewer/viewer.css").is_file())
        self.assertTrue((TARGET / "scripts/lib/play/journey_viewer/viewer.js").is_file())
        self.assertTrue((TARGET / "references/controller/command-log.md").is_file())
        self.assertTrue(
            (TARGET / "references/controller/command-log.schema.json").is_file()
        )
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

    def test_codex_skill_requires_explicit_invocation(self) -> None:
        source_metadata = (ROOT / "agents" / "openai.yaml").read_text()
        packaged_metadata = (TARGET / "agents" / "openai.yaml").read_text()

        self.assertIn("allow_implicit_invocation: false", source_metadata)
        self.assertEqual(source_metadata, packaged_metadata)

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

    def test_marketplace_declares_no_competing_hooks(self) -> None:
        hooks = json.loads((ROOT / "plugins/play/hooks/hooks.json").read_text())

        self.assertEqual({}, hooks["hooks"])

    def test_cursor_marketplace_points_at_the_cursor_plugin_payload(self) -> None:
        marketplace = json.loads(
            (ROOT / ".cursor-plugin/marketplace.json").read_text()
        )

        self.assertEqual("play-skills", marketplace["name"])
        self.assertEqual("./plugins/play", marketplace["plugins"][0]["source"])
        self.assertTrue((ROOT / "plugins/play/.cursor-plugin/plugin.json").is_file())

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
