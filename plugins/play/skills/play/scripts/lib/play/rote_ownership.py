"""Detect when rote owns this machine's Play installation.

rote installs Play under ``<ROTE_HOME>/play/{versions,current,install.json}``.
While that install record exists, rote is the only installer: Play's legacy
installers, activation, and recovery writers must not rewire the machine.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


MANAGED_INSTALL_COMMAND = ("rote", "install", "play")
MANAGED_INSTALL_TEXT = " ".join(MANAGED_INSTALL_COMMAND)


@dataclass(frozen=True)
class RoteManagedPlay:
    rote_home: Path
    record: Path
    rote_home_derived: bool

    def refusal(self, action: str) -> str:
        return (
            f"{action} is disabled because rote manages this Play installation "
            f"({self.record}). Run `{MANAGED_INSTALL_TEXT}` to install, update, or "
            "repair Play."
        )


def _versions_tree_home(play_root: Path) -> Path | None:
    """Return ROTE_HOME when ``play_root`` is ``<ROTE_HOME>/play/versions/<release>``."""

    root = play_root.resolve()
    versions = root.parent
    if versions.name == "versions" and versions.parent.name == "play":
        return versions.parent.parent
    return None


def rote_managed_play(
    play_root: Path, environ: Mapping[str, str] | None = None
) -> RoteManagedPlay | None:
    """Return rote's ownership of Play, or None when Play manages itself.

    A nonempty ROTE_HOME always selects the rote home; it never falls back to
    ``~/.rote``. Without it, a Play root inside a rote versions tree names its
    own rote home, so launchers that do not export ROTE_HOME stay in their home.
    """

    environment = os.environ if environ is None else environ
    tree_home = _versions_tree_home(play_root)
    configured = environment.get("ROTE_HOME", "")
    if configured:
        home = Path(configured).absolute()
        derived = False
    elif tree_home is not None:
        home = tree_home
        derived = True
    else:
        home = Path.home() / ".rote"
        derived = False
    record = home / "play" / "install.json"
    if record.exists() or tree_home is not None:
        return RoteManagedPlay(rote_home=home, record=record, rote_home_derived=derived)
    return None


def rote_managed_refusal(
    action: str, play_root: Path, environ: Mapping[str, str] | None = None
) -> str | None:
    """Return the refusal message for a legacy writer, or None when it may run."""

    managed = rote_managed_play(play_root, environ)
    return managed.refusal(action) if managed is not None else None
