"""Discoverable terminal facade for Play's operator commands."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from .identity import recover_rote_session


ROOT = Path(__file__).resolve().parents[3]
BIN = ROOT / "scripts" / "bin"
FIELD_GUIDE = "https://www.modiqo.ai/blog/play-cheat-sheet.md"


def version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def render_help() -> str:
    return f"""Play {version()} — reusable procedures and journey exploration

Usage:
  play --help
  play --version
  play <command> [arguments]

AGENT · DISCOVER AND RUN
  $play                         Search for the best reusable procedure
  $play what's new              Show recent shared procedures
  $play <play URI>              Run a known procedure
  play search <outcome>         Search local and authorized registry Plays

EXPLORE & VISUALIZE
  $play explore <outcome>       Start a Playmaker exploration
  play journey live             Open the active journey viewer
                                Alias: play-journey view --active
  play journey <operation> ...  snapshot, graph, story, scene, view, doctor,
                                refresh, rebuild, or worker

RECALL & REFERENCE
  play guide [topic]           Show the plain-language, harness-aware guide
  play journal [day]            Show today, yesterday, or YYYY-MM-DD
  play whats new                Show the last seven days and remember the digest
  play digest                   Alias: play whats new
  play cheat-sheet              Print the complete bundled field guide
  {FIELD_GUIDE}

RECURRING PLAYS · OPTIONAL TULVING
  play recurring probe          Check whether Tulving's clock is ready
  play recurring schedule ...   Validate, then schedule one exact Play
  play recurring list           List active schedules
  play recurring recall ...     Read run envelopes as JSON lines
  play recurring last [id]      Show the latest completed run envelope
  play recurring status         Show clock and ledger health
  play recurring clock on|off   Start or stop the OS timer
  play recurring update         Check for a Tulving update
  play schedule ...             Alias: play recurring schedule ...

ROUTING
  play routing ...              Inspect or configure direct-routing policy
  direct: <request>             Bypass Play for one agent request
  continue exploration          Return to a paused exploration

INSPECT & IMPROVE
  play audit <play URI|path>    Advisory report card for a pulled Play
  play audit <ref> --author     Author work order with owners and fixes
  play audit <ref> --profile stock-macos|ubuntu-lts
                                See the card as a stock consumer would
  play audit history <ref>      Timeline of audits for a Play
  play audit show <ref>         Render a stored audit

RECOVERY & DIAGNOSTICS
  play update ...               Download the latest Play and review its plan
  play backup ...               Manage Play backups
  play restore ...              Restore a Play backup
  play preflight ...            Check installation and runtime health

Run 'play <command> --help' for command-specific options.
Commands typed with '$play' are agent prompts; commands beginning with 'play' run in your shell.
"""


def _usage_error(message: str) -> int:
    print(f"play: {message}", file=sys.stderr)
    print("Run 'play --help' for the themed command index.", file=sys.stderr)
    return 2


def _execute(
    name: str,
    arguments: Sequence[str],
    executor: Callable[[str, list[str]], object],
) -> int:
    executable = BIN / name
    if not executable.is_file():
        print(f"play: bundled command is missing: {executable}", file=sys.stderr)
        return 1
    executor(str(executable), [str(executable), *arguments])
    return 0


def _render_update_help() -> str:
    return """Update Play through the same verified installer used for first setup.

Usage:
  play update [installer arguments]

Examples:
  play update
  play update --harness codex --harness cursor
  play update --yes

The updater downloads the latest official Play source over HTTPS, snapshots
Play-owned state, shows the convergence plan, and verifies or restores it.
Rote and Tulving keep their independent update checks and approvals.
"""


def _recover_search_identity() -> bool:
    rote = shutil.which("rote")
    if rote is None:
        return True
    try:
        status, provider = recover_rote_session(rote)
    except (OSError, subprocess.TimeoutExpired):
        print(
            "play: Rote identity check could not complete; credentials were not changed.",
            file=sys.stderr,
        )
        return False
    if status in {"authenticated", "recovered"}:
        return True
    if status == "required":
        if provider is None:
            print(
                "play: Rote login is required and no previous provider is recorded. "
                "Run `rote login --provider google` or `rote login --provider github`.",
                file=sys.stderr,
            )
        else:
            print(
                f"play: {provider.title()} sign-in did not complete; search has not run.",
                file=sys.stderr,
            )
        return False
    print(
        "play: Rote identity check failed without requesting login; search has not run.",
        file=sys.stderr,
    )
    return False


def main(
    argv: Sequence[str] | None = None,
    *,
    executor: Callable[[str, list[str]], object] = os.execv,
    identity_recoverer: Callable[[], bool] = _recover_search_identity,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"help", "-h", "--help"}:
        print(render_help(), end="")
        return 0
    if arguments[0] in {"version", "-V", "--version"}:
        print(f"play {version()}")
        return 0

    command, tail = arguments[0], arguments[1:]
    if command == "journey":
        if not tail:
            tail = ["--help"]
        elif tail[0] == "live":
            tail = ["view", "--active", *tail[1:]]
        return _execute("play-journey", tail, executor)

    if command == "journal":
        if tail and tail[0] in {"-h", "--help"}:
            return _execute("play-journal", tail, executor)
        day = tail[0] if tail and not tail[0].startswith("-") else "today"
        rest = tail[1:] if tail and not tail[0].startswith("-") else tail
        return _execute("play-journal", ["show", "--day", day, *rest], executor)

    if command in {"what's", "whats"} and tail[:1] == ["new"]:
        tail = tail[1:]
        command = "whats-new"

    if command in {"digest", "whats-new", "what's-new"}:
        digest_arguments = tail or ["--remember", "--days", "7"]
        return _execute("play-digest", digest_arguments, executor)

    if command == "cheat-sheet":
        if tail:
            return _usage_error("'cheat-sheet' takes no arguments")
        return _execute("play-cheat-sheet", [], executor)

    if command == "guide":
        return _execute("play-guide", tail, executor)

    if command == "search":
        if not identity_recoverer():
            return 1
        return _execute("play-search", tail or ["--help"], executor)

    if command == "update":
        if tail[:1] in (["-h"], ["--help"]):
            print(_render_update_help(), end="")
            return 0
        installer = ROOT / "install.sh"
        if not installer.is_file():
            print(f"play: bundled installer is missing: {installer}", file=sys.stderr)
            return 1
        executor("/bin/sh", ["/bin/sh", str(installer), *tail])
        return 0

    if command in {"recurring", "schedule"}:
        recurring_arguments = tail if command == "recurring" else ["schedule", *tail]
        if not recurring_arguments:
            recurring_arguments = ["--help"]
        return _execute("play-recurring", recurring_arguments, executor)

    delegated = {
        "audit": "play-audit",
        "routing": "play-routing",
        "backup": "play-bootstrap",
        "restore": "play-bootstrap",
        "preflight": "play-preflight",
    }
    if command in delegated:
        delegated_arguments = [command, *tail] if command in {"backup", "restore"} else tail
        if not delegated_arguments:
            delegated_arguments = ["--help"]
        return _execute(delegated[command], delegated_arguments, executor)

    return _usage_error(f"unknown command {command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
