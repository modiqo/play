"""Search local and authorized registry Plays concurrently and deduplicate results."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .commands import CommandError, run_json
from .normalize import NormalizationError, normalize_query, semantic_version_key
from .render import json_text


SCHEMA = "play.search/v1"
MAX_DESCRIPTION_CHARS = 480
_DISCOVERY_STOP_WORDS = {
    "a",
    "an",
    "and",
    "can",
    "fetch",
    "find",
    "for",
    "from",
    "get",
    "help",
    "in",
    "me",
    "month",
    "my",
    "of",
    "please",
    "retrieve",
    "the",
    "to",
    "want",
    "you",
}
_MONTHS = {
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec",
}


class SearchError(CommandError):
    pass


def discovery_queries(query: str) -> list[str]:
    """Return bounded broad-to-specific queries without model inference."""

    tokens = query.split()
    stable = [
        token
        for token in tokens
        if token not in _DISCOVERY_STOP_WORDS
        and token not in _MONTHS
        and not token.isdecimal()
    ]
    broad = " ".join(stable)
    return list(dict.fromkeys(candidate for candidate in (query, broad) if candidate))


def search_both(query: str, limit: int) -> tuple[dict, list]:
    fetch_limit = max(50, limit * 10)
    queries = discovery_queries(query)
    commands = {}
    for index, candidate in enumerate(queries):
        commands[("local", index)] = [
            "rote", "play", "search", candidate, "--limit", str(fetch_limit), "--json"
        ]
        commands[("registry", index)] = [
            "rote", "registry", "play", "search", candidate,
            "--limit", str(fetch_limit), "--json",
        ]
    with ThreadPoolExecutor(max_workers=len(commands)) as executor:
        pending = {
            key: executor.submit(run_json, command, error_type=SearchError)
            for key, command in commands.items()
        }
        results = {key: future.result() for key, future in pending.items()}

    local_flows = []
    seen_paths = set()
    registry_items = []
    seen_registry = set()
    for index in range(len(queries)):
        local = results[("local", index)]
        flows = local.get("flows") if isinstance(local, dict) else None
        if not isinstance(flows, list):
            raise SearchError("local search result has no flows array")
        for item in flows:
            key = item.get("path") if isinstance(item, dict) else None
            if key not in seen_paths:
                seen_paths.add(key)
                local_flows.append(item)
        registry = results[("registry", index)]
        if not isinstance(registry, list):
            raise SearchError("registry search result is not an array")
        for item in registry:
            key = (
                item.get("owner_slug"), item.get("skill_name"), item.get("version"),
                item.get("storage_path"),
            ) if isinstance(item, dict) else None
            if key not in seen_registry:
                seen_registry.add(key)
                registry_items.append(item)
    return {"flows": local_flows}, registry_items


def registry_scope(item: dict) -> str:
    visibility = item.get("visibility")
    storage_path = item.get("storage_path")
    if visibility == "public" or (
        isinstance(storage_path, str) and storage_path.startswith("community_")
    ):
        return "remote_public"
    return "remote_private"


def bounded_description(value: object) -> str:
    description = value if isinstance(value, str) else ""
    if len(description) <= MAX_DESCRIPTION_CHARS:
        return description
    return description[: MAX_DESCRIPTION_CHARS - 1].rstrip() + "…"


def fingerprint(name: str, description: str) -> str:
    try:
        normalized_description = normalize_query(description or name)
    except (SearchError, NormalizationError):
        normalized_description = ""
    return f"{normalize_query(name)}\0{normalized_description}"


def local_reference(path_value: str, flow_root: Path) -> str | None:
    path = Path(path_value).expanduser()
    try:
        relative = path.resolve(strict=False).relative_to(flow_root.resolve(strict=False))
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) >= 3 and parts[-1].startswith("main."):
        return f"{parts[0]}/{parts[1]}"
    return None


def preferred_local_path(paths: set[str], flow_root: Path) -> str:
    canonical = [path for path in paths if local_reference(path, flow_root)]
    return sorted(canonical or paths)[0]


def new_hit(name: str, description: str, reference: str | None) -> dict:
    return {
        "name": name,
        "description": description,
        "reference": reference,
        "version": None,
        "status": None,
        "sources": set(),
        "local_paths": set(),
        "source_ranks": {},
        "source_scores": {},
        "versions_by_scope": {},
    }


def merge_results(
    local_payload: dict,
    registry_payload: list,
    flow_root: Path,
    limit: int,
    normalized_query: str = "",
) -> list[dict]:
    local_flows = local_payload.get("flows") if isinstance(local_payload, dict) else None
    if not isinstance(local_flows, list):
        raise SearchError("local search result has no flows array")
    if not isinstance(registry_payload, list):
        raise SearchError("registry search result is not an array")

    canonical: dict[str, dict] = {}
    aliases = []

    for rank, item in enumerate(registry_payload, 1):
        if not isinstance(item, dict):
            raise SearchError("registry search contains an invalid item")
        owner = item.get("owner_slug")
        name = item.get("skill_name")
        if not isinstance(owner, str) or not isinstance(name, str):
            raise SearchError("registry search item lacks owner_slug or skill_name")
        reference = f"{owner}/{name}"
        description = bounded_description(item.get("skill_description"))
        hit = canonical.setdefault(reference, new_hit(name, description, reference))
        scope = registry_scope(item)
        hit["sources"].add(scope)
        hit["source_ranks"][scope] = min(rank, hit["source_ranks"].get(scope, rank))
        if isinstance(item.get("rank"), (int, float)):
            hit["source_scores"][scope] = max(
                float(item["rank"]), hit["source_scores"].get(scope, float("-inf"))
            )
        version = item.get("version")
        current_scope_version = hit["versions_by_scope"].get(scope)
        if semantic_version_key(version) > semantic_version_key(current_scope_version):
            hit["versions_by_scope"][scope] = version
        if semantic_version_key(version) > semantic_version_key(hit["version"]):
            hit["version"] = version
            hit["status"] = item.get("status")

    for rank, item in enumerate(local_flows, 1):
        if not isinstance(item, dict):
            raise SearchError("local search contains an invalid item")
        name = item.get("name")
        path_value = item.get("path")
        if not isinstance(name, str) or not isinstance(path_value, str):
            raise SearchError("local search item lacks name or path")
        description = bounded_description(item.get("description"))
        reference = local_reference(path_value, flow_root)
        if reference:
            hit = canonical.setdefault(reference, new_hit(name, description, reference))
            hit["sources"].add("local")
            hit["local_paths"].add(path_value)
            hit["source_ranks"]["local"] = min(rank, hit["source_ranks"].get("local", rank))
            if isinstance(item.get("score"), (int, float)):
                hit["source_scores"]["local"] = max(
                    float(item["score"]), hit["source_scores"].get("local", float("-inf"))
                )
        else:
            aliases.append((rank, item))

    references_by_fingerprint: dict[str, list[str]] = {}
    for reference, hit in canonical.items():
        references_by_fingerprint.setdefault(fingerprint(hit["name"], hit["description"]), []).append(reference)

    local_only: list[dict] = []
    for rank, item in aliases:
        matches = references_by_fingerprint.get(
            fingerprint(item["name"], item.get("description") or ""), []
        )
        local_matches = [reference for reference in matches if "local" in canonical[reference]["sources"]]
        if len(local_matches) == 1:
            hit = canonical[local_matches[0]]
        elif len(matches) == 1:
            hit = canonical[matches[0]]
        else:
            hit = new_hit(item["name"], bounded_description(item.get("description")), None)
            local_only.append(hit)
        hit["sources"].add("local")
        hit["local_paths"].add(item["path"])
        hit["source_ranks"]["local"] = min(rank, hit["source_ranks"].get("local", rank))
        if isinstance(item.get("score"), (int, float)):
            hit["source_scores"]["local"] = max(
                float(item["score"]), hit["source_scores"].get("local", float("-inf"))
            )

    hits = [*canonical.values(), *local_only]
    discovery = discovery_queries(normalized_query)
    semantic_query = discovery[-1] if discovery else normalized_query
    query_tokens = set(semantic_query.split())
    for hit in hits:
        searchable = set(normalize_query(f"{hit['name']} {hit['description']}").split())
        coverage = len(query_tokens & searchable) / len(query_tokens) if query_tokens else 0.0
        rank_fusion = sum(1.0 / (60 + rank) for rank in hit["source_ranks"].values())
        hit["combined_score"] = coverage + rank_fusion
        hit["coverage"] = coverage
        hit["match_classification"] = (
            "full" if coverage >= 0.75 else "partial" if coverage >= 0.34 else "uncertain"
        )
        hit["primary_scope"] = (
            "local" if "local" in hit["sources"]
            else "remote_private" if "remote_private" in hit["sources"]
            else "remote_public"
        )
    class_priority = {"full": 0, "partial": 1, "uncertain": 2}
    scope_priority = {"local": 0, "remote_private": 1, "remote_public": 2}
    hits.sort(key=lambda hit: (
        class_priority[hit["match_classification"]],
        scope_priority[hit["primary_scope"]],
        -hit["combined_score"],
        hit["name"].casefold(),
        hit["reference"] or "",
    ))

    output = []
    for hit in hits[:limit]:
        reference = hit["reference"]
        primary_scope = hit["primary_scope"]
        if primary_scope == "local":
            path = preferred_local_path(hit["local_paths"], flow_root)
            exact_reference = path
            uri = Path(path).expanduser().resolve(strict=False).as_uri()
            run_command = shlex.join(["rote", "play", "run", path])
            inspect_command = shlex.join(["rote", "play", "inspect", path, "--json"])
            hint_kind = "local-play"
            local_availability = "found" if reference else "local_only"
            execution_resolution = "run_local"
            candidate_reference = path
        elif reference:
            selected_version = hit["versions_by_scope"].get(primary_scope) or hit["version"]
            exact_reference = f"{reference}@{selected_version}" if selected_version else reference
            uri = f"https://play.modiqo.ai/{exact_reference}"
            run_command = shlex.join(["rote", "play", "run", exact_reference])
            inspect_command = shlex.join(["rote", "play", "inspect", exact_reference, "--json"])
            hint_kind = "play"
            local_availability = "found" if "local" in hit["sources"] else "not_found"
            execution_resolution = "pull_required"
            candidate_reference = exact_reference
        else:
            raise SearchError("search result has neither a local path nor registry reference")
        output.append(
            {
                "name": hit["name"],
                "description": hit["description"],
                "reference": candidate_reference,
                "exact_reference": exact_reference,
                "version": hit["version"],
                "status": hit["status"],
                "sources": sorted(hit["sources"]),
                "score": round(hit["combined_score"], 8),
                "coverage": round(hit["coverage"], 8),
                "match_classification": hit["match_classification"],
                "primary_scope": primary_scope,
                "uri": uri,
                "run_command": run_command,
                "inspect_command": inspect_command,
                "hint_kind": hint_kind,
                "local_availability": local_availability,
                "execution_resolution": execution_resolution,
                "selection_description": (
                    f"{hit['description']} Already local; inspect and run without a pull prompt."
                    if execution_resolution == "run_local"
                    else f"{hit['description']} Remote {primary_scope.removeprefix('remote_').replace('_', ' ')} match; pulling requires your approval."
                ),
            }
        )
    return output


def render_markdown(original: str, normalized: str, results: list[dict]) -> str:
    lines = [f"Search: `{normalized}`", "", "Sources: local + authorized registry"]
    if original.strip().casefold() != normalized:
        lines.extend(["", f"Normalized from: {original.strip()}"])
    if not results:
        return "\n".join([*lines, "", "No matching Plays found."])
    for index, result in enumerate(results, 1):
        source = " + ".join(result["sources"])
        version = f" · v{result['version']}" if result["version"] else ""
        lines.extend(
            [
                "",
                f"{index}. **{result['name']}** · {source}{version} · score {result['score']:.8f}",
                f"   URI: {result['uri']}",
                (
                    "   Local: found; the outcome route runs it immediately after read-only inspection."
                    if result["execution_resolution"] == "run_local"
                    else "   Remote: not local; pull/install requires approval."
                ),
            ]
        )
        lines.append(f"   Next: inspect with `{result['inspect_command']}`")
        if result["execution_resolution"] == "pull_required":
            lines.append("   Pulling and running requires a separate approval after inspection.")
    return "\n".join(lines)


def build_play_choices(results: list[dict]) -> list[dict]:
    """Return harness-ready choices for all runnable Plays."""
    choices = []
    for result in results:
        reference = result.get("reference")
        if not isinstance(reference, str) or not reference:
            continue
        owner = (
            result.get("primary_scope", "local").replace("remote_", "")
            if result.get("primary_scope") != "local"
            else "local"
        )
        choices.append(
            {
                "reference": reference,
                "label": f"{result['name']} — {owner}",
                "description": result["selection_description"],
                "parameters": {},
            }
        )
    return choices


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="+", help="natural-language Play search query")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    original = " ".join(args.query)
    try:
        normalized = normalize_query(original)
        local_payload, registry_payload = search_both(normalized, args.limit)
        results = merge_results(
            local_payload,
            registry_payload,
            Path(os.environ.get("ROTE_FLOW_DIR", Path.home() / ".rote" / "flows")),
            args.limit,
            normalized,
        )
    except (SearchError, NormalizationError) as error:
        print(f"play-search: {error}", file=sys.stderr)
        return 1
    payload = {
        "schema": SCHEMA,
        "query": original,
        "normalized_query": normalized,
        "complete": True,
        "sources": ["local", "remote_private", "remote_public"],
        "result_refs": [result["reference"] for result in results if result["reference"]],
        "results": results,
        "play_choices": build_play_choices(results),
    }
    if args.as_json:
        print(json_text(payload))
    else:
        print(render_markdown(original, normalized, results))
    return 0
