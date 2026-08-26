"""Discoverable terminal facade for Play's operator commands."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path


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

EXPLORE & VISUALIZE
  $play explore <outcome>       Start a Playmaker exploration
  play journey live             Open the active journey viewer
                                Alias: play-journey view --active
  play journey <operation> ...  snapshot, graph, story, scene, view, doctor,
                                refresh, rebuild, or worker

RECALL & REFERENCE
  play journal [day]            Show today, yesterday, or YYYY-MM-DD
  play digest                   Show the last seven days and remember the digest
  play cheat-sheet              Print the complete bundled field guide
  {FIELD_GUIDE}

RECURRING PLAYS · OPTIONAL TULVING
  play recurring probe          Check whether Tulving's clock is ready
  play recurring schedule ...   Schedule one exact versioned Play
  play schedule ...             Alias: play recurring schedule ...

ROUTING
  play routing ...              Inspect or configure direct-routing policy
  direct: <request>             Bypass Play for one agent request
  continue exploration          Return to a paused exploration

RECOVERY & DIAGNOSTICS
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

    if command in {"digest", "whats-new", "what's-new"}:
        digest_arguments = tail or ["--remember", "--days", "7"]
        return _execute("play-digest", digest_arguments, executor)

    if command == "cheat-sheet":
        if tail:
            return _usage_error("'cheat-sheet' takes no arguments")
        return _execute("play-cheat-sheet", [], executor)

    if command in {"recurring", "schedule"}:
        recurring_arguments = tail if command == "recurring" else ["schedule", *tail]
        if not recurring_arguments:
            recurring_arguments = ["--help"]
        return _execute("play-recurring", recurring_arguments, executor)

    delegated = {
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
