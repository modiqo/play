"""Corpus evaluation: measure the audit against every Play it can reach.

    play-audit-corpus refs [--query ...]      registry search terms → one reference per line
    play-audit-corpus run <refs-file> <dir>   audit each reference, keep the pulled package and envelope
    play-audit-corpus report <dir> [RULE]     per-rule counts, disk cross-check of every fact, evidence

The cross-check re-derives each fact from the package with independent code
(regex and tomllib, not the audit's own extractors). A fact the checker cannot
confirm is a contradiction to investigate, and the report exits 1 on any.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import fetch
from .runner import safe_audit

try:
    import tomllib as _toml
except ImportError:  # pragma: no cover
    _toml = None  # type: ignore[assignment]

DEFAULT_QUERIES = (
    "git", "github", "python", "docker", "ci", "weather", "audit", "report", "secrets", "release",
    "calendar", "notion", "review", "deploy", "test", "lint", "security", "env", "repo", "pr",
)
_REFERENCE = re.compile(r'"reference":\s*"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@[0-9.]+"')


def registry_references(queries: Sequence[str]) -> list[str]:
    found: set[str] = set()
    for query in queries:
        try:
            completed = subprocess.run(
                ["rote", "play", "search", query, "--source", "registry", "--json"],
                capture_output=True, text=True, check=False, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        found.update(_REFERENCE.findall(completed.stdout))
    return sorted(found)


def run(refs: Sequence[str], out_dir: Path, *, read_adapters: bool = True) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for reference in refs:
        owner, _, name = reference.partition("/")
        pulled, error = fetch.pull(owner, name)
        if pulled is None:
            (out_dir / f"{owner}__{name}.err").write_text(error or "pull failed")
            failures += 1
            continue
        envelope = safe_audit(pulled.root, reference=reference, read_adapters=read_adapters, persist=False)
        envelope.setdefault("subject", {})["kept_at"] = str(pulled.root)
        (out_dir / f"{owner}__{name}.json").write_text(json.dumps(envelope, indent=1, sort_keys=True))
        print(f"{reference:50s} {envelope.get('status')}  facts {envelope.get('summary', {}).get('open_facts')}")
    return failures


def _load(out_dir: Path) -> list[dict[str, Any]]:
    envelopes = []
    for path in sorted(out_dir.glob("*.json")):
        try:
            envelopes.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            print(f"unreadable envelope: {path.name}")
    return envelopes


def _tools(root: Path) -> dict[str, dict[str, Any]] | None:
    deps = root / "deps.toml"
    if not deps.is_file() or _toml is None:
        return None if not deps.is_file() else {}
    try:
        data = _toml.loads(deps.read_text())
    except ValueError:
        return {}
    tools: dict[str, dict[str, Any]] = {}
    for entry in data.get("tools", []):
        command = str(entry.get("command") or entry.get("id") or "").rsplit("/", 1)[-1]
        if command:
            tools[command] = entry
    return tools


def _step_block(frontmatter: str, step: str) -> str | None:
    match = re.search(
        r"^\s*\*\s{3}%s:\s*$(.*?)(?=^\s*\*\s{3}[A-Za-z_][\w-]*:\s*$|\* ---)" % re.escape(step),
        frontmatter, re.S | re.M,
    )
    return match.group(1) if match else None


def verify_fact(root: Path, finding: dict[str, Any]) -> bool | None:
    """Independently confirm one fact from the package. None means not checkable here."""
    rule_id, ev, loc = finding["id"], finding.get("evidence", {}), finding.get("location", {})
    main = (root / "main.ts").read_text(errors="replace") if (root / "main.ts").is_file() else ""
    frontmatter = main[: main.find("*/") + 2] if "*/" in main else main
    tools = _tools(root)
    if rule_id == "DEPS_TOML_MISSING":
        return tools is None
    if rule_id == "STEP_NO_TIMEOUT":
        return all((block := _step_block(frontmatter, s)) is not None and "timeout_ms" not in block for s in ev["step"].split(", "))
    if rule_id == "PARAMETERS_UNDER_METADATA":
        return re.search(r"^\s*\*\s{3}parameters:", frontmatter, re.M) is not None and re.search(r"^\s*\*\sparameters:", frontmatter, re.M) is None
    if rule_id == "BODY_STRANDED":
        return "import.meta.main" in main and "steps_with_presentation" not in frontmatter and re.search(r"^\s*\*\ssteps:", frontmatter, re.M) is not None
    if rule_id == "INLINE_CODE_PAYLOAD":
        return ev["length"] > 256
    if rule_id == "RESOURCE_MISSING":
        return not (root / "resources" / ev["resource"]).exists()
    if rule_id == "INTERPRETER_FLOOR_MISSING":
        return tools is not None and ev["command"] in tools and not tools[ev["command"]].get("version_requirement")
    if rule_id == "TOOL_UNDECLARED":
        return tools is not None and ev["command"] not in tools
    if rule_id in {"SUBPROCESS_UNDECLARED", "DENO_COMMAND_UNDECLARED", "CHILD_PROCESS_UNDECLARED", "ROTE_EXEC_UNDECLARED"}:
        source = (root / loc["file"]).read_text(errors="replace")
        return tools is not None and ev["command"] not in tools and re.search(r"""["']%s\b""" % re.escape(ev["command"]), source) is not None
    if rule_id == "FANOUT_OVER_PREVIEW":
        return "stdout.text" in ev["source"] and "for_each" in frontmatter
    if rule_id == "ABSOLUTE_HOME_PATH":
        return ev["path"] in frontmatter
    if rule_id == "PY_FLOOR_TOO_LOW":
        line = (root / loc["file"]).read_text(errors="replace").splitlines()[loc["line"] - 1]
        return ("|" in line and ("->" in line or ":" in line)) if "union" in ev["construct"] else True
    if rule_id == "DEPENDS_ON_UNKNOWN":
        return _step_block(frontmatter, ev["target"]) is None
    if rule_id == "ADAPTER_SOURCE_PROVENANCE_DIFFERS":
        return ev["pinned"] in frontmatter and ev["pinned"] != ev["installed"]
    return None


def report(out_dir: Path, only: str | None = None) -> int:
    envelopes = _load(out_dir)
    print(f"envelopes {len(envelopes)}  status {dict(collections.Counter(e.get('status') for e in envelopes))}")
    hits: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = collections.defaultdict(list)
    unknowns: collections.Counter[str] = collections.Counter()
    for e in envelopes:
        for section in ("facts", "judgments"):
            for f in e.get(section, []):
                hits[f["id"]].append((section, e, f))
        for u in e.get("unknowns", []):
            unknowns[u["kind"]] += 1
    print("\nper-rule  plays / hits")
    for rule_id, items in sorted(hits.items(), key=lambda kv: -len(kv[1])):
        plays = {e["subject"]["reference"] for _, e, _ in items}
        print(f"  {items[0][0]:9s} {rule_id:45s} {len(plays):4d} / {len(items):4d}")
    print("\nunknowns:", dict(unknowns))

    verified: collections.Counter[str] = collections.Counter()
    contradicted: list[tuple[str, str, dict[str, Any]]] = []
    for e in envelopes:
        kept = e.get("subject", {}).get("kept_at")
        if not kept or not Path(kept).is_dir():
            continue
        for f in e.get("facts", []):
            try:
                ok = verify_fact(Path(kept), f)
            except Exception as error:  # noqa: BLE001
                ok = None
                print(f"  checker error on {e['subject']['reference']} {f['id']}: {error}")
            if ok is True:
                verified[f["id"]] += 1
            elif ok is False:
                contradicted.append((e["subject"]["reference"], f["id"], f.get("evidence", {})))
    print("\nfacts cross-checked against the package on disk:")
    for rule_id, n in sorted(verified.items()):
        print(f"  {rule_id:45s} verified {n:4d}")
    print(f"  contradicted: {len(contradicted)}")
    for item in contradicted:
        print("   ", item)

    if only:
        print(f"\n=== {only}")
        for _, e, f in hits.get(only, []):
            loc = f.get("location", {})
            where = loc.get("path") or (f"{loc.get('file')}:{loc.get('line')}" if loc.get("line") else loc.get("file", ""))
            print(f"- {e['subject']['reference']:45s} {where}")
            print(f"    {f['message'][:160]}")
            kept = e.get("subject", {}).get("kept_at")
            if kept and loc.get("file") and loc.get("line"):
                try:
                    print("    | " + (Path(kept) / loc["file"]).read_text(errors="replace").splitlines()[loc["line"] - 1].strip()[:110])
                except (OSError, IndexError):
                    pass
    return 1 if contradicted else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="play-audit-corpus", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    refs = sub.add_parser("refs")
    refs.add_argument("--query", action="append", default=None)
    runner = sub.add_parser("run")
    runner.add_argument("refs_file")
    runner.add_argument("out_dir")
    runner.add_argument("--no-adapters", action="store_true")
    rep = sub.add_parser("report")
    rep.add_argument("out_dir")
    rep.add_argument("rule", nargs="?")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "refs":
        for reference in registry_references(args.query or DEFAULT_QUERIES):
            print(reference)
        return 0
    if args.command == "run":
        references = [line.strip() for line in Path(args.refs_file).read_text().splitlines() if line.strip()]
        failures = run(references, Path(args.out_dir), read_adapters=not args.no_adapters)
        print(f"pull failures: {failures}")
        return 0
    return report(Path(args.out_dir), args.rule)
