from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.lib.play.package import ROOT, TARGET, differences, materialize


class PluginPackageTest(unittest.TestCase):
    def test_payload_is_exactly_the_pointer(self) -> None:
        files = sorted(
            str(path.relative_to(TARGET)) for path in TARGET.rglob("*") if path.is_file()
        )

        self.assertEqual(["SKILL.md", "agents/openai.yaml"], files)

    def test_payload_matches_source(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            expected = Path(temporary) / "play"
            materialize(expected)
            self.assertEqual([], differences(expected, TARGET))

    def test_pointer_keeps_play_discovery_and_names_rote_install(self) -> None:
        source = (ROOT / "SKILL.md").read_text()
        pointer = (TARGET / "SKILL.md").read_text()
        frontmatter = source[: source.index("\n---\n", 4) + len("\n---\n")]

        self.assertTrue(pointer.startswith(frontmatter))
        self.assertIn("name: play\n", frontmatter)
        self.assertIn("${ROTE_HOME:-$HOME/.rote}/play/current/SKILL.md", pointer)
        self.assertIn("curl -fsSL https://getrote.dev/install | bash", pointer)
        self.assertIn("rote install play", pointer)

    def test_codex_skill_requires_explicit_invocation(self) -> None:
        source_metadata = (ROOT / "agents" / "openai.yaml").read_text()
        packaged_metadata = (TARGET / "agents" / "openai.yaml").read_text()

        self.assertIn("allow_implicit_invocation: false", source_metadata)
        self.assertEqual(source_metadata, packaged_metadata)

    def test_plugin_versions_match_the_packaged_version(self) -> None:
        expected = (ROOT / "VERSION").read_text().strip()
        manifests = (
            ROOT / "plugins/play/package.json",
            ROOT / "plugins/play/.codex-plugin/plugin.json",
            ROOT / "plugins/play/.claude-plugin/plugin.json",
            ROOT / "plugins/play/.kimi-plugin/plugin.json",
            ROOT / "plugins/play/.cursor-plugin/plugin.json",
        )
        for manifest in manifests:
            self.assertEqual(expected, json.loads(manifest.read_text())["version"])

    def test_claude_plugin_declares_no_dependencies(self) -> None:
        manifest = json.loads(
            (ROOT / "plugins/play/.claude-plugin/plugin.json").read_text()
        )

        self.assertNotIn("dependencies", manifest)

    def test_marketplace_declares_no_competing_hooks(self) -> None:
        hooks = json.loads((ROOT / "plugins/play/hooks/hooks.json").read_text())

        self.assertEqual({}, hooks["hooks"])

    def test_marketplaces_keep_the_play_plugin_identity(self) -> None:
        for marketplace_path in (
            ".claude-plugin/marketplace.json",
            ".agents/plugins/marketplace.json",
        ):
            marketplace = json.loads((ROOT / marketplace_path).read_text())
            self.assertEqual("play-skills", marketplace["name"])
            self.assertEqual("play", marketplace["plugins"][0]["name"])
        for manifest in (".claude-plugin", ".codex-plugin"):
            plugin = json.loads((ROOT / "plugins/play" / manifest / "plugin.json").read_text())
            self.assertEqual("play", plugin["name"])
            self.assertEqual("./skills/", plugin["skills"])

    def test_cursor_marketplace_points_at_the_cursor_plugin_payload(self) -> None:
        marketplace = json.loads(
            (ROOT / ".cursor-plugin/marketplace.json").read_text()
        )

        self.assertEqual("play-skills", marketplace["name"])
        self.assertEqual("./plugins/play", marketplace["plugins"][0]["source"])
        self.assertTrue((ROOT / "plugins/play/.cursor-plugin/plugin.json").is_file())

    def test_active_sources_have_no_legacy_flow_commands(self) -> None:
        files = [ROOT / "README.md", ROOT / "SKILL.md"]
        for directory in (ROOT / "references", ROOT / "scripts"):
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
