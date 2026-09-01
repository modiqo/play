from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.lib.play.rote_workspace_layout import (
    resolve_rote_workspace_layout,
    rote_workspace_root,
    workspace_layout_warning,
)


class RoteWorkspaceLayoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.rote_home = Path(self.temporary.name) / "rote-home"
        self.environment = {"ROTE_HOME": str(self.rote_home)}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def add_workspace(root: Path, name: str) -> Path:
        workspace = root / name
        database = workspace / ".rote" / "workspace.db"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"workspace")
        return workspace

    def test_current_root_is_the_default_without_workspaces(self) -> None:
        layout = resolve_rote_workspace_layout(self.environment)

        self.assertEqual(self.rote_home / "workspaces", layout.selected_root)
        self.assertFalse(layout.split)

    def test_current_root_wins_when_it_contains_workspaces(self) -> None:
        current = self.rote_home / "workspaces"
        self.add_workspace(current, "current")

        self.assertEqual(current, rote_workspace_root(self.environment))

    def test_legacy_root_is_the_backward_compatible_fallback(self) -> None:
        legacy = self.rote_home / "rote" / "workspaces"
        self.add_workspace(legacy, "legacy")

        self.assertEqual(legacy, rote_workspace_root(self.environment))

    def test_empty_current_root_does_not_hide_legacy_workspaces(self) -> None:
        current = self.rote_home / "workspaces"
        current.mkdir(parents=True)
        legacy = self.rote_home / "rote" / "workspaces"
        self.add_workspace(legacy, "legacy")

        self.assertEqual(legacy, rote_workspace_root(self.environment))

    def test_split_roots_prefer_current_and_return_a_warning(self) -> None:
        current = self.rote_home / "workspaces"
        legacy = self.rote_home / "rote" / "workspaces"
        self.add_workspace(current, "current")
        self.add_workspace(legacy, "legacy")

        layout = resolve_rote_workspace_layout(self.environment)
        warning = workspace_layout_warning(layout)

        self.assertEqual(current, layout.selected_root)
        self.assertTrue(layout.split)
        self.assertIsNotNone(warning)
        assert warning is not None
        self.assertIn(str(current), warning)
        self.assertIn(str(legacy), warning)

    def test_non_workspace_directories_do_not_select_the_legacy_root(self) -> None:
        legacy = self.rote_home / "rote" / "workspaces" / "notes"
        legacy.mkdir(parents=True)

        self.assertEqual(
            self.rote_home / "workspaces",
            rote_workspace_root(self.environment),
        )
