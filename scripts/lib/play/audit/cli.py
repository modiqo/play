"""``play-audit``: audit a Play package and render one of its surfaces.

    play-audit <path|reference> [--card|--author|--json|--report]
                                [--profile stock-macos|ubuntu-lts|live]
                                [--no-adapters] [--no-store]
    play-audit history <reference> [--json]
    play-audit show <reference> [--at <digest>] [--card|--author|--json|--report]

Exit code is always 0. The audit is advisory; nothing branches on it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import fetch, render, store
from .host import PROFILES
from .runner import safe_audit, unavailable

_REFERENCE = re.compile(r"^(?:https://play\.modiqo\.ai/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:@([A-Za-z0-9_.-]+))?/?$")


def _flows_root() -> Path:
    override = os.environ.get("ROTE_HOME")
    return (Path(override) if override else Path.home() / ".rote") / "flows"


def resolve_target(target: str) -> tuple[Path | None, str]:
    """A directory, a main.ts, or ``owner/name[@version]`` (URL form accepted)."""
    path = Path(target).expanduser()
    if path.is_file() and path.name.endswith(".ts"):
        return path.parent, f"{path.parent.parent.name}/{path.parent.name}"
    if path.is_dir():
        return path, f"{path.parent.name}/{path.name}"
    match = _REFERENCE.match(target)
    if match:
        owner, name = match.group(1), match.group(2)
        candidate = _flows_root() / owner / name
        return (candidate if candidate.is_dir() else None), f"{owner}/{name}"
    return None, target


def requested_version(target: str) -> str | None:
    match = _REFERENCE.match(target)
    return match.group(3) if match else None


def audit_target(
    target: str,
    *,
    profile: str | None = None,
    read_adapters: bool = True,
    persist: bool = True,
    pull: bool = True,
    keep: bool = False,
) -> dict[str, Any]:
    """Audit an installed Play, or pull one the user can access into a temporary home first."""
    root, reference = resolve_target(target)
    if root is not None:
        return safe_audit(root, reference=reference, profile=profile, read_adapters=read_adapters, persist=persist)
    match = _REFERENCE.match(target)
    if match is None:
        return unavailable(reference, f"{target} is neither an installed Play, a path, nor an owner/name reference")
    if not pull:
        return unavailable(reference, f"no installed Play at {reference}; pull it first or pass a path")
    pulled, error = fetch.pull(match.group(1), match.group(2))
    if pulled is None:
        return unavailable(reference, error or "pull failed")
    try:
        envelope = safe_audit(pulled.root, reference=reference, profile=profile, read_adapters=read_adapters, persist=persist)
        subject = envelope.setdefault("subject", {})
        subject["source"] = "pulled"
        wanted = match.group(3)
        if wanted and subject.get("version") and wanted != subject["version"]:
            envelope.setdefault("unknowns", []).append({
                "kind": "VERSION_DIFFERS", "subject": reference,
                "reason": f"requested @{wanted}; the registry pull provided @{subject['version']} (pull takes the latest release)",
            })
            summary = envelope.setdefault("summary", {})
            summary["unknowns"] = len(envelope["unknowns"])
        if keep:
            subject["kept_at"] = str(pulled.root)
        return envelope
    finally:
        if not keep:
            pulled.cleanup()


def _render(envelope: dict[str, Any], mode: str) -> str:
    if mode == "json":
        return json.dumps(envelope, indent=1, sort_keys=True)
    if mode == "author":
        return render.author(envelope)
    if mode == "report":
        return render.report(envelope)
    return render.card(envelope)


def _mode(args: argparse.Namespace) -> str:
    for mode in ("json", "author", "report", "card"):
        if getattr(args, mode, False):
            return mode
    return "card"


def _add_modes(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--card", action="store_true", help="consumer report card (default)")
    group.add_argument("--author", action="store_true", help="author work order with owners and fixes")
    group.add_argument("--json", action="store_true", help="the envelope")
    group.add_argument("--report", action="store_true", help="Markdown for the registry inbox")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="play-audit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="audit a package (default when the first argument is a path or reference)")
    run.add_argument("target")
    _add_modes(run)
    run.add_argument("--profile", choices=["live", *PROFILES], default="live")
    run.add_argument("--no-adapters", action="store_true", help="skip rote adapter metadata reads")
    run.add_argument("--no-store", action="store_true", help="do not persist under PLAY_HOME")
    run.add_argument("--no-pull", action="store_true", help="never pull; audit only an installed Play or a path")
    run.add_argument("--keep", action="store_true", help="keep the temporary pull and print its path")

    hist = sub.add_parser("history", help="timeline of audits for a Play")
    hist.add_argument("reference")
    hist.add_argument("--json", action="store_true")

    show = sub.add_parser("show", help="render a stored envelope")
    show.add_argument("reference")
    show.add_argument("--at", dest="digest", help="package digest of the envelope to show")
    _add_modes(show)
    return parser


def _normalize(argv: Sequence[str]) -> list[str]:
    """Let ``play-audit <target> ...`` mean ``play-audit run <target> ...``."""
    args = list(argv)
    if args and args[0] not in {"run", "history", "show", "-h", "--help"} and not args[0].startswith("-"):
        args.insert(0, "run")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(_normalize(sys.argv[1:] if argv is None else argv))
    if args.command == "history":
        entries = store.history(args.reference)
        if args.json:
            print(json.dumps(entries, indent=1, sort_keys=True))
        elif not entries:
            print(f"no audits recorded for {args.reference}")
        else:
            print(render.history(entries))
        return 0
    if args.command == "show":
        envelope = store.load(args.reference, digest=args.digest)
        if envelope is None:
            print(f"no stored audit for {args.reference}" + (f" at {args.digest}" if args.digest else ""))
            return 0
        print(_render(envelope, _mode(args)))
        return 0

    envelope = audit_target(
        args.target, profile=args.profile, read_adapters=not args.no_adapters,
        persist=not args.no_store, pull=not args.no_pull, keep=args.keep,
    )
    output = _render(envelope, _mode(args))
    if args.keep and envelope.get("subject", {}).get("kept_at"):
        print(f"kept: {envelope['subject']['kept_at']}", file=sys.stderr)
    if output:
        print(output)
    elif envelope.get("status") != "ok":
        print(f"audit unavailable: {envelope.get('reason')}", file=sys.stderr)
    return 0
