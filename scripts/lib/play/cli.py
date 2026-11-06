"""Terminal facade for what Play keeps beside its rote journey pack.

`play recurring` schedules Plays through Tulving. `play journey` and `play audit`
are developer tooling. Agent requests go through rote: `/play <outcome>` runs
`rote journey next`.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BIN = ROOT / "scripts" / "bin"


def version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def render_help() -> str:
    return f"""Play {version()} — recurring Plays and journey tooling

Usage:
  play --help
  play --version
  play <command> [arguments]

Agent requests run on rote: /play <outcome> hands the request to
`rote journey next`. Install with rote's install.sh --pack play.

RECURRING PLAYS · TULVING
  play recurring probe          Check whether Tulving's clock is ready
  play recurring schedule ...   Validate, then schedule one exact Play
  play recurring list           List active schedules
  play recurring recall ...     Read run envelopes as JSON lines
  play recurring last [id]      Show the latest completed run envelope
  play recurring status         Show clock and ledger health
  play recurring clock on|off   Start or stop the OS timer
  play recurring update         Check for a Tulving update
  play schedule ...             Alias: play recurring schedule ...

DEVELOPER TOOLING
  play journey live             Open the active journey viewer
                                Alias: play-journey view --active
  play journey <operation> ...  snapshot, graph, story, scene, view, doctor,
                                refresh, rebuild, or worker
  play audit <play URI|path>    Advisory report card for a pulled Play
  play audit <ref> --author     Author work order with owners and fixes
  play audit history <ref>      Timeline of audits, rehearsals, and handoffs
  play audit rehearse <path>    See the Play as consumers will; prove negative cases

Run 'play <command> --help' for command-specific options.
"""


def _usage_error(message: str) -> int:
    print(f"play: {message}", file=sys.stderr)
    print("Run 'play --help' for the command index.", file=sys.stderr)
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


def main(
    argv: Sequence[str] | None = None,
    *,
    executor: Callable[[str, list[str]], object] = os.execv,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"help", "-h", "--help"}:
        print(render_help(), end="")
        return 0
    if arguments[0] in {"version", "-V", "--version"}:
        print(f"play {version()}")
        return 0

    command, tail = arguments[0], arguments[1:]
    if command in {"recurring", "schedule"}:
        recurring_arguments = tail if command == "recurring" else ["schedule", *tail]
        return _execute("play-recurring", recurring_arguments or ["--help"], executor)

    if command == "journey":
        if not tail:
            tail = ["--help"]
        elif tail[0] == "live":
            tail = ["view", "--active", *tail[1:]]
        return _execute("play-journey", tail, executor)

    if command == "audit":
        return _execute("play-audit", tail or ["--help"], executor)

    return _usage_error(f"unknown command {command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
