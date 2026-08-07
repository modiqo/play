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


class SearchError(CommandError):
    pass


def search_both(query: str, limit: int) -> tuple[dict, list]:
    fetch_limit = max(50, limit * 10)
    commands = {
        "local": ["rote", "play", "search", query, "--limit", str(fetch_limit), "--json"],
        "registry": [
            "rote",
            "registry",
            "play",
            "search",
            query,
            "--limit",
            str(fetch_limit),
            "--json",
        ],
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = {
            source: executor.submit(run_json, command, error_type=SearchError)
            for source, command in commands.items()
        }
        results = {source: future.result() for source, future in pending.items()}
    return results["local"], results["registry"]


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
        description = item.get("skill_description") or ""
        hit = canonical.setdefault(reference, new_hit(name, description, reference))
        hit["sources"].add("registry")
        hit["source_ranks"]["registry"] = min(rank, hit["source_ranks"].get("registry", rank))
        if isinstance(item.get("rank"), (int, float)):
            hit["source_scores"]["registry"] = max(
                float(item["rank"]), hit["source_scores"].get("registry", float("-inf"))
            )
        version = item.get("version")
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
        description = item.get("description") or ""
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
            hit = new_hit(item["name"], item.get("description") or "", None)
            local_only.append(hit)
        hit["sources"].add("local")
        hit["local_paths"].add(item["path"])
        hit["source_ranks"]["local"] = min(rank, hit["source_ranks"].get("local", rank))
        if isinstance(item.get("score"), (int, float)):
            hit["source_scores"]["local"] = max(
                float(item["score"]), hit["source_scores"].get("local", float("-inf"))
            )

    hits = [*canonical.values(), *local_only]
    query_tokens = set(normalized_query.split())
    for hit in hits:
        searchable = set(normalize_query(f"{hit['name']} {hit['description']}").split())
        coverage = len(query_tokens & searchable) / len(query_tokens) if query_tokens else 0.0
        rank_fusion = sum(1.0 / (60 + rank) for rank in hit["source_ranks"].values())
        hit["combined_score"] = coverage + rank_fusion
    hits.sort(key=lambda hit: (-hit["combined_score"], hit["name"].casefold(), hit["reference"] or ""))

    output = []
    for hit in hits[:limit]:
        reference = hit["reference"]
        if reference and "registry" in hit["sources"]:
            exact_reference = f"{reference}@{hit['version']}" if hit["version"] else reference
            uri = f"https://play.modiqo.ai/{exact_reference}"
            run_command = shlex.join(["rote", "play", "run", exact_reference])
            inspect_command = shlex.join(["rote", "play", "inspect", exact_reference, "--json"])
            hint_kind = "play"
            local_availability = "found" if "local" in hit["sources"] else "not_found"
            execution_resolution = (
                "inspect_required" if local_availability == "found" else "pull_expected"
            )
        else:
            path = sorted(hit["local_paths"])[0]
            uri = Path(path).expanduser().resolve(strict=False).as_uri()
            run_command = shlex.join(["rote", "play", "run", path])
            inspect_command = ""
            hint_kind = "local-play"
            exact_reference = None
            local_availability = "local_only"
            execution_resolution = "publish_required"
        output.append(
            {
                "name": hit["name"],
                "description": hit["description"],
                "reference": reference if "registry" in hit["sources"] else None,
                "exact_reference": exact_reference,
                "version": hit["version"],
                "status": hit["status"],
                "sources": sorted(hit["sources"]),
                "score": round(hit["combined_score"], 8),
                "uri": uri,
                "run_command": run_command,
                "inspect_command": inspect_command,
                "hint_kind": hint_kind,
                "local_availability": local_availability,
                "execution_resolution": execution_resolution,
                "selection_description": (
                    f"{hit['description']} Available in an authorized organization; "
                    "a local pull/install is expected and will require approval."
                    if execution_resolution == "pull_expected"
                    else (
                        f"{hit['description']} Inspect dependencies and effects before approval."
                        if execution_resolution == "inspect_required"
                        else f"{hit['description']} Publish this local Flow to make it a runnable Play."
                    )
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
                    "   Local: not found; pull/install expected after approval."
                    if result["execution_resolution"] == "pull_expected"
                    else (
                        "   Local: found; inspection will verify the exact installed version."
                        if result["execution_resolution"] == "inspect_required"
                        else "   Local-only Flow: no authorized registry Play was found."
                    )
                ),
            ]
        )
        if result["hint_kind"] == "play":
            lines.append(f"   Next: inspect with `{result['inspect_command']}`")
            lines.append("   Running still requires a separate approval after inspection.")
        else:
            lines.append("   Publish it to obtain a first-class Play reference.")
    return "\n".join(lines)


def build_play_choices(results: list[dict]) -> list[dict]:
    """Return harness-ready choices for registry Plays only."""
    choices = []
    for result in results:
        exact_reference = result.get("exact_reference")
        if not isinstance(exact_reference, str) or not exact_reference:
            continue
        owner = exact_reference.split("/", 1)[0]
        choices.append(
            {
                "reference": exact_reference,
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
        "sources": ["local", "authorized_registry"],
        "result_refs": [result["reference"] for result in results if result["reference"]],
        "results": results,
        "play_choices": build_play_choices(results),
    }
    if args.as_json:
        print(json_text(payload))
    else:
        print(render_markdown(original, normalized, results))
    return 0
