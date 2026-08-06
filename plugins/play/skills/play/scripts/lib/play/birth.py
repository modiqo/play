"""Owner-private Play birth certificate capture, binding, and rendering."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .commands import CommandError, run_rote_json
from .digest_state import canonical_json, stable_sha
from .private_store import PrivateStoreError, atomic_write_json, ensure_private_directory, load_json, locked_store


BIRTH_SCHEMA = "play.birth/v1"
INDEX_SCHEMA = "play.birth-index/v1"


class BirthError(ValueError):
    """A birth certificate cannot be captured, resolved, or verified."""


def default_home() -> Path:
    configured = os.environ.get("PLAY_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".play"


def _empty_index() -> dict[str, Any]:
    return {
        "schema": INDEX_SCHEMA,
        "by_birth_sha": {},
        "by_exact_reference": {},
        "by_flow_fingerprint": {},
        "by_registry_content_hash": {},
    }


def _paths(home: Path) -> tuple[Path, Path, Path]:
    root = home / "births"
    return root, root / "objects", root / "index.json"


def _load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_index()
    try:
        payload = load_json(path)
    except PrivateStoreError as error:
        raise BirthError(str(error)) from error
    required_maps = (
        "by_birth_sha",
        "by_exact_reference",
        "by_flow_fingerprint",
        "by_registry_content_hash",
    )
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != INDEX_SCHEMA
        or any(not isinstance(payload.get(key), dict) for key in required_maps)
    ):
        raise BirthError(f"birth index must use {INDEX_SCHEMA}")
    return payload


def _write_index(path: Path, index: dict[str, Any]) -> None:
    try:
        atomic_write_json(path, index)
    except PrivateStoreError as error:
        raise BirthError(str(error)) from error


def _require_dict(payload: object, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BirthError(f"{label} is not a JSON object")
    return payload


def _require_list(payload: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise BirthError(f"{label} is not a JSON object array")
    return payload


def _safe_package(flow: dict[str, Any]) -> tuple[dict[str, Any], str]:
    package = _require_dict(flow.get("package"), "Flow package")
    root_value = package.get("root")
    members = package.get("members")
    if not isinstance(root_value, str) or not isinstance(members, list):
        raise BirthError("Flow package lacks its root or members")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise BirthError(f"Flow package root does not exist: {root}")

    fingerprints: list[dict[str, Any]] = []
    for member in members:
        if not isinstance(member, dict) or not isinstance(member.get("path"), str):
            raise BirthError("Flow package contains an invalid member")
        if member.get("class") == "local":
            continue
        relative = Path(member["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise BirthError(f"Flow package member escapes its root: {relative}")
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise BirthError(f"Flow package member escapes its root: {relative}") from error
        if not candidate.is_file():
            raise BirthError(f"Flow package member is not a file: {relative}")
        try:
            content = candidate.read_bytes()
        except OSError as error:
            raise BirthError(f"Cannot read Flow package member {relative}: {error}") from error
        fingerprints.append(
            {
                "path": relative.as_posix(),
                "class": member.get("class") or "unknown",
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    if not fingerprints:
        raise BirthError("Flow package has no portable artifact members")
    fingerprints.sort(key=lambda item: item["path"])
    safe = {
        "entry": package.get("entry"),
        "files": len(fingerprints),
        "bytes": sum(item["bytes"] for item in fingerprints),
        "members": fingerprints,
    }
    return safe, stable_sha(safe)


def _unsupported_trace_json(error: CommandError) -> bool:
    message = str(error).casefold()
    return "--json" in message and any(
        phrase in message
        for phrase in ("unexpected argument", "unknown option", "unknown flag", "unrecognized option")
    )


def _trace_evidence(workspace: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    try:
        payload = run_rote_json("trace", "--deps", "--json", working_directory=workspace)
    except CommandError as error:
        if not _unsupported_trace_json(error):
            raise BirthError(f"cannot capture dependency trace: {error}") from error
        try:
            commands = run_rote_json(
                "workspace", "inspect", "log", "--json", working_directory=workspace
            )
            dependencies = run_rote_json(
                "workspace", "inspect", "deps", "--json", working_directory=workspace
            )
        except CommandError as fallback_error:
            raise BirthError(f"cannot capture workspace evidence: {fallback_error}") from fallback_error
        return (
            _require_list(commands, "workspace command log"),
            _require_list(dependencies, "workspace dependency trace"),
            "workspace-inspect-json-fallback",
        )

    trace = _require_dict(payload, "dependency trace")
    commands = trace.get("commands", trace.get("log"))
    dependencies = trace.get("dependencies", trace.get("deps"))
    return (
        _require_list(commands, "dependency trace commands"),
        _require_list(dependencies, "dependency trace dependencies"),
        "rote-trace-deps-json",
    )


def _response_count(value: object) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return 0
        return len(parsed) if isinstance(parsed, list) else 0
    return 0


def _timestamp_summary(commands: list[dict[str, Any]]) -> tuple[str | None, str | None, float | None]:
    timestamps = sorted(
        item["timestamp"]
        for item in commands
        if isinstance(item.get("timestamp"), str) and item["timestamp"]
    )
    if not timestamps:
        return None, None, None
    try:
        start = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
        end = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
    except ValueError:
        return timestamps[0], timestamps[-1], None
    return timestamps[0], timestamps[-1], max(0.0, (end - start).total_seconds())


def _modalities(command_types: Counter[str]) -> list[str]:
    found: set[str] = set()
    for command in command_types:
        folded = command.casefold()
        if folded.startswith("process"):
            found.add("shell")
        if folded.startswith(("query", "session")):
            found.add("adapter")
        if "browser" in folded or "playwright" in folded:
            found.add("browser")
    return sorted(found)


def _safe_integer_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, int) and item >= 0
    }


def _journey(stats: dict[str, Any], commands: list[dict[str, Any]], dependencies: list[dict[str, Any]]) -> dict[str, Any]:
    command_types: Counter[str] = Counter(
        item["command_type"]
        for item in commands
        if isinstance(item.get("command_type"), str)
    )
    dependency_types: Counter[str] = Counter(
        item["dependency_type"]
        for item in dependencies
        if isinstance(item.get("dependency_type"), str)
    )
    started_at, ended_at, duration_seconds = _timestamp_summary(commands)
    edges = [
        {
            "command_sequence": item.get("command_sequence"),
            "dependency_type": item.get("dependency_type"),
            "source_response": item.get("source_response"),
        }
        for item in dependencies
        if isinstance(item.get("command_sequence"), int)
        and isinstance(item.get("dependency_type"), str)
        and isinstance(item.get("source_response"), int)
    ]
    return {
        "commands": stats.get("commands") if isinstance(stats.get("commands"), int) else len(commands),
        "responses": stats.get("responses") if isinstance(stats.get("responses"), int) else sum(_response_count(item.get("response_ids")) for item in commands),
        "variables": stats.get("variables") if isinstance(stats.get("variables"), int) else None,
        "execution_mode": stats.get("execution_mode") if isinstance(stats.get("execution_mode"), str) else None,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration_seconds,
        "command_types": dict(sorted(command_types.items())),
        "dependency_types": dict(sorted(dependency_types.items())),
        "dependency_edges": edges,
        "modalities": _modalities(command_types),
        "token_savings": _safe_integer_map(stats.get("token_savings")),
    }


def capture_birth(workspace_selector: str, flow_selector: str, *, home: Path | None = None) -> dict[str, Any]:
    home = home or default_home()
    try:
        flow = _require_dict(run_rote_json("flow", "info", flow_selector, "--json"), "Flow info")
    except CommandError as error:
        raise BirthError(str(error)) from error
    if flow.get("status") != "released":
        raise BirthError("birth capture requires a released Flow")
    artifact, flow_fingerprint = _safe_package(flow)
    _, _, index_path = _paths(home)
    index = _load_index(index_path)
    existing_sha = index["by_flow_fingerprint"].get(flow_fingerprint)
    if isinstance(existing_sha, str):
        return _capture_result(existing_sha, _load_record(home, existing_sha), created=False, home=home)

    try:
        stats = _require_dict(
            run_rote_json("workspace", "stats", workspace_selector, "--json"), "workspace stats"
        )
    except CommandError as error:
        raise BirthError(str(error)) from error
    location = stats.get("location")
    if not isinstance(location, str):
        raise BirthError("workspace stats lacks a location")
    workspace = Path(location).expanduser().resolve()
    if not workspace.is_dir():
        raise BirthError(f"workspace does not exist: {workspace}")

    commands, dependencies, trace_method = _trace_evidence(workspace)
    captured_at = datetime.now(timezone.utc).isoformat()
    record = {
        "schema": BIRTH_SCHEMA,
        "captured_at": captured_at,
        "workspace": {
            "name": stats.get("name") if isinstance(stats.get("name"), str) else workspace.name,
        },
        "flow": {
            "name": flow.get("name"),
            "description": flow.get("description") or "",
            "format": flow.get("format"),
            "scheme": flow.get("scheme"),
            "version": flow.get("version"),
            "kind": flow.get("kind"),
            "flow_type": flow.get("flow_type"),
            "execution_model": flow.get("execution_model"),
            "requires_endpoints": sorted(flow.get("requires_endpoints") or []),
            "requires_sessions": flow.get("requires_sessions") is True,
            "fingerprint": flow_fingerprint,
            "artifact": artifact,
        },
        "journey": _journey(stats, commands, dependencies),
        "sources": {
            "flow": "rote-flow-info-json",
            "stats": "rote-workspace-stats-json",
            "trace": trace_method,
        },
        "privacy": {
            "owner_local_only": True,
            "raw_commands_excluded": True,
            "raw_parameters_excluded": True,
            "raw_queries_excluded": True,
            "raw_responses_excluded": True,
            "workspace_path_excluded": True,
        },
    }
    birth_sha = stable_sha(record)
    root, objects, index_path = _paths(home)
    ensure_private_directory(objects)
    with locked_store(root):
        index = _load_index(index_path)
        existing_sha = index["by_flow_fingerprint"].get(flow_fingerprint)
        if isinstance(existing_sha, str):
            existing = _load_record(home, existing_sha)
            return _capture_result(existing_sha, existing, created=False, home=home)
        object_path = objects / f"{birth_sha}.json"
        if object_path.exists():
            existing = _load_record(home, birth_sha)
            if existing != record:
                raise BirthError(f"birth object collision at {birth_sha}")
        else:
            try:
                atomic_write_json(object_path, record)
            except PrivateStoreError as error:
                raise BirthError(str(error)) from error
        index["by_flow_fingerprint"][flow_fingerprint] = birth_sha
        index["by_birth_sha"][birth_sha] = {
            "flow_name": flow.get("name"),
            "flow_fingerprint": flow_fingerprint,
            "captured_at": captured_at,
            "exact_references": [],
            "bindings": {},
        }
        _write_index(index_path, index)
    return _capture_result(birth_sha, record, created=True, home=home)


def _capture_result(sha: str, record: dict[str, Any], *, created: bool, home: Path) -> dict[str, Any]:
    return {
        "schema": "play.birth-capture-result/v1",
        "created": created,
        "sha256": sha,
        "flow_fingerprint": record["flow"]["fingerprint"],
        "object_ref": str(_paths(home)[1] / f"{sha}.json"),
        "capture_ref": sha,
    }


def _load_record(home: Path, sha: str) -> dict[str, Any]:
    object_path = _paths(home)[1] / f"{sha}.json"
    try:
        record = load_json(object_path)
    except FileNotFoundError as error:
        raise BirthError(f"birth object is missing: {sha}") from error
    except PrivateStoreError as error:
        raise BirthError(str(error)) from error
    if not isinstance(record, dict) or record.get("schema") != BIRTH_SCHEMA:
        raise BirthError(f"birth object {sha} must use {BIRTH_SCHEMA}")
    return record


def _candidate_shas(index: dict[str, Any], selector: str) -> set[str]:
    candidates: set[str] = set()
    if selector in index["by_birth_sha"]:
        candidates.add(selector)
    candidates.update(sha for sha in index["by_birth_sha"] if sha.startswith(selector))
    exact = index["by_exact_reference"].get(selector)
    if isinstance(exact, str):
        candidates.add(exact)
    content = index["by_registry_content_hash"].get(selector)
    if isinstance(content, str):
        candidates.add(content)
    fingerprint = index["by_flow_fingerprint"].get(selector)
    if isinstance(fingerprint, str):
        candidates.add(fingerprint)
    for sha, metadata in index["by_birth_sha"].items():
        if not isinstance(metadata, dict):
            continue
        if metadata.get("flow_name") == selector:
            candidates.add(sha)
        if any(
            isinstance(reference, str)
            and (reference == selector or reference.partition("/")[2].partition("@")[0] == selector)
            for reference in metadata.get("exact_references", [])
        ):
            candidates.add(sha)
    return candidates


def resolve_birth(selector: str, *, home: Path | None = None) -> tuple[str, dict[str, Any], dict[str, Any]]:
    home = home or default_home()
    index = _load_index(_paths(home)[2])
    candidates = _candidate_shas(index, selector)
    if not candidates:
        raise BirthError(f"no owner-local birth certificate matches {selector!r}")
    if len(candidates) > 1:
        choices = ", ".join(sorted(value[:12] for value in candidates))
        raise BirthError(f"birth selector {selector!r} is ambiguous: {choices}")
    sha = next(iter(candidates))
    return sha, _load_record(home, sha), index


def _registry_release(reference: str) -> tuple[str, str, str | None]:
    base, marker, requested_version = reference.partition("@")
    if "/" not in base:
        raise BirthError("Play reference must be owner/name or owner/name@version")
    try:
        payload = _require_dict(
            run_rote_json("registry", "flow", "info", base, "--json"), "registry Flow info"
        )
    except CommandError as error:
        raise BirthError(str(error)) from error
    version = _require_dict(payload.get("version"), "registry Flow version")
    resolved_version = version.get("version")
    content_hash = version.get("content_hash")
    if not isinstance(resolved_version, str) or not resolved_version:
        raise BirthError("registry Flow info lacks a version")
    if marker and requested_version != resolved_version:
        raise BirthError(
            f"requested {base}@{requested_version}, but registry reports {base}@{resolved_version}"
        )
    if not isinstance(content_hash, str) or not content_hash:
        raise BirthError("registry Flow info lacks a content hash")
    metadata = version.get("metadata")
    provenance = metadata.get("provenance") if isinstance(metadata, dict) else None
    author_value = provenance.get("author") if isinstance(provenance, dict) else None
    author = author_value.strip() if isinstance(author_value, str) and author_value.strip() else None
    return f"{base}@{resolved_version}", content_hash, author


def bind_birth(selector: str, reference: str, *, home: Path | None = None) -> dict[str, Any]:
    home = home or default_home()
    sha, record, _ = resolve_birth(selector, home=home)
    exact_reference, content_hash, author = _registry_release(reference)
    root, _, index_path = _paths(home)
    with locked_store(root):
        index = _load_index(index_path)
        for mapping, key, label in (
            (index["by_exact_reference"], exact_reference, "exact reference"),
            (index["by_registry_content_hash"], content_hash, "registry content hash"),
        ):
            existing = mapping.get(key)
            if isinstance(existing, str) and existing != sha:
                raise BirthError(f"{label} is already bound to another birth certificate")
        index["by_exact_reference"][exact_reference] = sha
        index["by_registry_content_hash"][content_hash] = sha
        metadata = index["by_birth_sha"].get(sha)
        if not isinstance(metadata, dict):
            raise BirthError(f"birth index is missing metadata for {sha}")
        references = metadata.setdefault("exact_references", [])
        if not isinstance(references, list) or any(not isinstance(item, str) for item in references):
            raise BirthError(f"birth index has invalid references for {sha}")
        if exact_reference not in references:
            references.append(exact_reference)
            references.sort()
        binding_record = {
            "registry_content_hash": content_hash,
            "author": author,
            "author_status": "available" if author else "unavailable",
        }
        bindings = metadata.setdefault("bindings", {})
        if not isinstance(bindings, dict):
            raise BirthError(f"birth index has invalid bindings for {sha}")
        existing_binding = bindings.get(exact_reference)
        if existing_binding is not None and existing_binding != binding_record:
            raise BirthError("exact reference already has different local provenance")
        bindings[exact_reference] = binding_record
        _write_index(index_path, index)
    return {
        "schema": "play.birth-binding-result/v1",
        "sha256": sha,
        "exact_reference": exact_reference,
        "registry_content_hash": content_hash,
        "author": author,
        "author_status": "available" if author else "unavailable",
        "binding_ref": exact_reference,
        "flow_fingerprint": record["flow"]["fingerprint"],
    }


def birth_listing(*, home: Path | None = None) -> dict[str, Any]:
    home = home or default_home()
    index = _load_index(_paths(home)[2])
    items = [
        {"sha256": sha, **metadata}
        for sha, metadata in index["by_birth_sha"].items()
        if isinstance(metadata, dict)
    ]
    items.sort(key=lambda item: (item.get("captured_at") or "", item["sha256"]), reverse=True)
    return {"schema": "play.birth-list/v1", "count": len(items), "births": items}


def verify_birth(selector: str, *, home: Path | None = None) -> dict[str, Any]:
    home = home or default_home()
    sha, record, index = resolve_birth(selector, home=home)
    computed = stable_sha(record)
    metadata = index["by_birth_sha"].get(sha)
    fingerprint = record.get("flow", {}).get("fingerprint")
    checks = {
        "object_hash_matches": computed == sha,
        "birth_index_matches": isinstance(metadata, dict),
        "flow_fingerprint_matches": index["by_flow_fingerprint"].get(fingerprint) == sha,
        "reference_bindings_match": isinstance(metadata, dict)
        and all(index["by_exact_reference"].get(ref) == sha for ref in metadata.get("exact_references", [])),
    }
    return {
        "schema": "play.birth-verification/v1",
        "sha256": sha,
        "valid": all(checks.values()),
        "checks": checks,
    }


def _render_record(sha: str, record: dict[str, Any], index: dict[str, Any]) -> str:
    flow = record["flow"]
    journey = record["journey"]
    metadata = index["by_birth_sha"].get(sha, {})
    references_value = metadata.get("exact_references", []) if isinstance(metadata, dict) else []
    references = references_value if isinstance(references_value, list) else []
    bindings_value = metadata.get("bindings", {}) if isinstance(metadata, dict) else {}
    bindings = bindings_value if isinstance(bindings_value, dict) else {}
    authors = sorted(
        {
            binding["author"]
            for binding in bindings.values()
            if isinstance(binding, dict) and isinstance(binding.get("author"), str)
        }
    )
    lines = [
        f"# Birth certificate: {flow['name']}",
        "",
        flow.get("description") or "No description recorded.",
        "",
        f"- Birth SHA: `{sha}`",
        f"- Flow fingerprint: `{flow['fingerprint']}`",
        f"- Captured: {record['captured_at']}",
        f"- Workspace: {record['workspace']['name']}",
        f"- Published as: {', '.join(f'`{item}`' for item in references) if references else 'not bound yet'}",
        f"- Publication author: {', '.join(authors) if authors else 'unavailable'}",
        f"- Artifact: {flow['artifact']['files']} files, {flow['artifact']['bytes']} bytes",
        f"- Journey: {journey['commands']} commands, {journey['responses']} responses, {journey['variables']} variables",
        f"- Modalities learned: {', '.join(journey['modalities']) if journey['modalities'] else 'none detected'}",
        f"- Dependency edges: {len(journey['dependency_edges'])}",
        f"- Token savings: {journey['token_savings'].get('tokens_saved', 0)}",
        "",
        "This owner-local certificate excludes raw commands, parameters, queries, responses, and workspace paths.",
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="play-birth", description=__doc__)
    parser.add_argument("--home", type=Path, help="Override the owner-private Play home")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def command_options(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--home", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS
        )
        command_parser.add_argument(
            "--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS
        )

    capture = subparsers.add_parser("capture", help="Capture a released Flow's one-time birth")
    command_options(capture)
    capture.add_argument("--workspace", required=True)
    capture.add_argument("--flow", required=True)

    bind = subparsers.add_parser("bind", help="Bind a birth to its minted exact Play reference")
    command_options(bind)
    bind.add_argument("selector")
    bind.add_argument("--reference", required=True)

    show = subparsers.add_parser("show", help="Render one owner-local birth certificate")
    command_options(show)
    show.add_argument("selector")

    listing = subparsers.add_parser("list", help="List owner-local birth certificates")
    command_options(listing)

    verify = subparsers.add_parser("verify", help="Verify a birth object and its index links")
    command_options(verify)
    verify.add_argument("selector")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            payload = capture_birth(args.workspace, args.flow, home=args.home)
        elif args.command == "bind":
            payload = bind_birth(args.selector, args.reference, home=args.home)
        elif args.command == "list":
            payload = birth_listing(home=args.home)
        elif args.command == "verify":
            payload = verify_birth(args.selector, home=args.home)
        else:
            sha, record, index = resolve_birth(args.selector, home=args.home)
            if not args.json:
                print(_render_record(sha, record, index))
                return 0
            bindings = index["by_birth_sha"].get(sha)
            references = bindings.get("exact_references", []) if isinstance(bindings, dict) else []
            payload = {
                "schema": "play.birth-show/v1",
                "sha256": sha,
                "flow_fingerprint": record["flow"]["fingerprint"],
                "object_ref": str(_paths(args.home or default_home())[1] / f"{sha}.json"),
                "exact_reference": references[0] if len(references) == 1 else None,
                "exact_references": references,
                "binding_ref": references[0] if len(references) == 1 else None,
                "record": record,
                "bindings": bindings,
            }
    except (BirthError, PrivateStoreError) as error:
        print(f"play-birth: {error}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
