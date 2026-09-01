"""Resolve current and legacy Rote workspace layouts without moving data."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RoteWorkspaceLayout:
    """One read-only decision across Rote's current and legacy workspace roots."""

    current_root: Path
    legacy_root: Path
    selected_root: Path
    current_has_workspaces: bool
    legacy_has_workspaces: bool

    @property
    def split(self) -> bool:
        return self.current_has_workspaces and self.legacy_has_workspaces


def _rote_home(environment: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environment is None else environment
    override = values.get("ROTE_HOME")
    return Path(override) if override else Path.home() / ".rote"


def _has_workspaces(root: Path) -> bool:
    """Return whether one root contains a valid Rote workspace database."""

    try:
        return any(
            not candidate.name.startswith(".")
            and candidate.is_dir()
            and (candidate / ".rote" / "workspace.db").is_file()
            for candidate in root.iterdir()
        )
    except OSError:
        return False


def resolve_rote_workspace_layout(
    environment: Mapping[str, str] | None = None,
) -> RoteWorkspaceLayout:
    """Prefer Rote's current root and fall back to its legacy vendor root."""

    rote_home = _rote_home(environment)
    current_root = rote_home / "workspaces"
    legacy_root = rote_home / "rote" / "workspaces"
    current_has_workspaces = _has_workspaces(current_root)
    legacy_has_workspaces = _has_workspaces(legacy_root)
    selected_root = (
        legacy_root
        if legacy_has_workspaces and not current_has_workspaces
        else current_root
    )
    return RoteWorkspaceLayout(
        current_root=current_root,
        legacy_root=legacy_root,
        selected_root=selected_root,
        current_has_workspaces=current_has_workspaces,
        legacy_has_workspaces=legacy_has_workspaces,
    )


def rote_workspace_root(environment: Mapping[str, str] | None = None) -> Path:
    return resolve_rote_workspace_layout(environment).selected_root


def workspace_layout_warning(layout: RoteWorkspaceLayout) -> str | None:
    if not layout.split:
        return None
    return (
        f"Rote workspaces exist in both {layout.current_root} and the legacy "
        f"root {layout.legacy_root}; using {layout.current_root}. Move legacy "
        "workspaces manually before removing the old root."
    )
