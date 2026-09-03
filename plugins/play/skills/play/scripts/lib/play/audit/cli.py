"""``play-audit``: audit a Play package and render one of its surfaces.

    play-audit <path|reference> [--card|--author|--json|--report]
                                [--profile stock-macos|ubuntu-lts|live]
                                [--no-adapters] [--no-store]
    play-audit history <reference> [--json]
    play-audit show <reference> [--at <digest>] [--card|--author|--json|--report]
    play-audit fixtures <path> [--from-run <input.json>] [--dry-run]     create side
    play-audit rehearse <path> [--profile live,stock-macos,ubuntu-lts] [--no-lint] [--json]
    play-audit handoff <ref|path> [--all | --rule ID ...] [--close [--run-ref X]]
    play-audit send <ref|path> [--out <file>]
    play-audit corpus refs|run|report ...

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

from . import cases, corpus, fetch, handoff, render, store
from . import package as package_mod
from . import rehearse as rehearse_mod
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

    fixtures = sub.add_parser("fixtures", help="pack positive fixtures from the last run and negative cases per step")
    fixtures.add_argument("path")
    fixtures.add_argument("--from-run", dest="from_run", help="a presentation input.json to take observations from")
    fixtures.add_argument("--dry-run", action="store_true", help="list what would be written")

    reh = sub.add_parser("rehearse", help="cards per host profile, lint, and the packed negative cases")
    reh.add_argument("path")
    reh.add_argument("--profile", default=",".join(rehearse_mod.DEFAULT_PROFILES), help="comma-separated: live,stock-macos,ubuntu-lts")
    reh.add_argument("--no-lint", action="store_true")
    reh.add_argument("--json", action="store_true")
    reh.add_argument("--no-store", action="store_true")

    hand = sub.add_parser("handoff", help="write a fix packet for chosen findings, or close one and record the delta")
    hand.add_argument("target")
    hand.add_argument("--all", action="store_true", help="every open finding")
    hand.add_argument("--rule", action="append", default=[], help="rule id to include (repeatable)")
    hand.add_argument("--close", action="store_true", help="re-audit and record what closed since the last packet")
    hand.add_argument("--run-ref", dest="run_ref", help="the troubleshooting run that applied the fixes")
    hand.add_argument("--json", action="store_true")

    send = sub.add_parser("send", help="write the author report for a Play you did not write")
    send.add_argument("target")
    send.add_argument("--out", help="file to write instead of the Play's report folder")

    corp = sub.add_parser("corpus", help="precision measurement over the registry (see play-audit-corpus)")
    corp.add_argument("rest", nargs=argparse.REMAINDER)
    return parser


_SUBCOMMANDS = {"run", "history", "show", "fixtures", "rehearse", "handoff", "send", "corpus", "-h", "--help"}


def _normalize(argv: Sequence[str]) -> list[str]:
    """Let ``play-audit <target> ...`` mean ``play-audit run <target> ...``."""
    args = list(argv)
    if args and args[0] not in _SUBCOMMANDS and not args[0].startswith("-"):
        args.insert(0, "run")
    return args


def _package_root(target: str) -> tuple[Path | None, str]:
    root, reference = resolve_target(target)
    return root, reference


def _fixtures(args: argparse.Namespace) -> int:
    root, reference = _package_root(args.path)
    if root is None:
        print(f"no Play package at {args.path}; pass the directory that holds main.ts", file=sys.stderr)
        return 0
    package = package_mod.load(root, reference)
    recorded = None
    source = Path(args.from_run) if args.from_run else cases.latest_run_input(str(package.frontmatter.data.get("name") or root.name))
    if source is not None and source.is_file():
        try:
            recorded = json.loads(source.read_text())
        except (OSError, json.JSONDecodeError) as error:
            print(f"could not read {source}: {error}", file=sys.stderr)
    else:
        print("no recorded run found; positive fixtures need one (run the Play once, or pass --from-run)", file=sys.stderr)
    result = cases.scaffold(package, recorded, write=not args.dry_run)
    verb = "would write" if args.dry_run else "wrote"
    for path in result.written:
        print(f"{verb}  {path}")
    for note in result.skipped:
        print(f"skipped {note}")
    if result.declared:
        print(("would declare" if args.dry_run else "declared") + " presentation_fixtures for: " + ", ".join(result.declared))
    if not args.dry_run and result.written:
        print("nothing here is referenced by a step, so `rote play run` will not execute it; `rote play lint` runs the positives, `play audit rehearse` the negatives")
    return 0


def _rehearse(args: argparse.Namespace) -> int:
    root, reference = _package_root(args.path)
    if root is None:
        print(f"no Play package at {args.path}", file=sys.stderr)
        return 0
    profiles = tuple(p.strip() for p in args.profile.split(",") if p.strip())
    result = rehearse_mod.rehearse(root, profiles=profiles, reference=reference, run_lint=not args.no_lint, persist=not args.no_store)
    print(json.dumps(result.to_dict(), indent=1, sort_keys=True) if args.json else rehearse_mod.render_text(result))
    return 0


def _handoff(args: argparse.Namespace) -> int:
    root, reference = _package_root(args.target)
    if root is None:
        print(f"no installed Play at {args.target}; handoff works on a local package", file=sys.stderr)
        return 0
    if args.close:
        result = handoff.close(reference, root, run_ref=args.run_ref)
        print(json.dumps(result, indent=1, sort_keys=True) if args.json else handoff.render_delta(result))
        return 0
    rule_ids = None if args.all or not args.rule else list(args.rule)
    packet, path, error = handoff.create(reference, root, rule_ids=rule_ids)
    if error:
        print(error, file=sys.stderr)
        return 0
    if args.json:
        print(json.dumps(packet, indent=1, sort_keys=True))
    else:
        print(handoff.render_packet(packet))
        print(f"\nwritten: {path}")
    return 0


def _send(args: argparse.Namespace) -> int:
    envelope = audit_target(args.target, persist=True)
    text = render.report(envelope)
    if args.out:
        Path(args.out).write_text(text)
        print(f"report written: {args.out}")
        return 0
    reference = str(envelope.get("subject", {}).get("reference") or "local/unknown")
    directory = store._play_dir(reference) / "reports"  # noqa: SLF001
    try:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{store._safe(envelope.get('subject', {}).get('audited_at') or 'report')}.md"  # noqa: SLF001
        target.write_text(text)
        print(f"report written: {target}")
        print("the registry has no inbox for reports yet; share this file with the author (their handle is the owner in the reference)")
    except OSError as error:
        print(text)
        print(f"could not store the report ({error}); printed above", file=sys.stderr)
    return 0


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
    if args.command == "fixtures":
        return _fixtures(args)
    if args.command == "rehearse":
        return _rehearse(args)
    if args.command == "handoff":
        return _handoff(args)
    if args.command == "send":
        return _send(args)
    if args.command == "corpus":
        return corpus.main(list(args.rest))

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
