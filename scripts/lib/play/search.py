"""Search local and authorized registry Plays concurrently and deduplicate results."""

from __future__ import annotations

import argparse
import difflib
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
    catalog_items, catalog_complete = _catalog_snapshot()
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
        results = {}
        source_errors: dict[tuple[str, int], str] = {}
        for key, future in pending.items():
            try:
                results[key] = future.result()
            except SearchError as error:
                source_errors[key] = str(error)

    local_flows = []
    seen_paths = set()
    live_registry_items = []
    for index in range(len(queries)):
        local = results.get(("local", index))
        if local is not None:
            flows = local.get("flows") if isinstance(local, dict) else None
            if not isinstance(flows, list):
                source_errors[("local", index)] = "local search result has no flows array"
            else:
                for item in flows:
                    key = item.get("path") if isinstance(item, dict) else None
                    if key not in seen_paths:
                        seen_paths.add(key)
                        local_flows.append(item)
        registry = results.get(("registry", index))
        if registry is not None:
            if not isinstance(registry, list):
                source_errors[("registry", index)] = (
                    "registry search result is not an array"
                )
            else:
                live_registry_items.extend(registry)
    if source_errors and not catalog_complete:
        details = "; ".join(
            f"{source}[{index}]: {message}"
            for (source, index), message in sorted(source_errors.items())
        )
        raise SearchError(
            f"live search was incomplete and no verified complete catalog cache was available: {details}"
        )
    # The registry's lexical search can miss an exactly-named Play the user is
    # authorized to run. The cached hub catalog is the authoritative bounded
    # enumeration of authorized-org Plays, so merge it as a recall backstop;
    # live results keep rank priority, and adequacy scoring decides matches.
    return {
        "flows": local_flows,
        "source_health": {
            "catalog_cache": "complete" if catalog_complete else "unavailable",
            "live_errors": [
                {
                    "source": source,
                    "query": queries[index],
                    "error": message,
                }
                for (source, index), message in sorted(source_errors.items())
            ],
        },
    }, reconcile_registry_items(
        live_registry_items, catalog_items
    )


def _registry_reference(item: dict) -> tuple[str, str] | None:
    owner = item.get("owner_slug")
    name = item.get("skill_name")
    if isinstance(owner, str) and owner and isinstance(name, str) and name:
        return owner, name
    return None


def _registry_skill_id(item: dict) -> str | None:
    value = item.get("skill_id")
    return value if isinstance(value, str) and value else None


def reconcile_registry_items(live_items: list, catalog_items: list[dict]) -> list[dict]:
    """Overlay authoritative catalog identity and visibility onto live search hits."""

    catalog_by_id = {
        skill_id: item
        for item in catalog_items
        if (skill_id := _registry_skill_id(item)) is not None
    }
    catalog_by_reference = {
        reference: item
        for item in catalog_items
        if (reference := _registry_reference(item)) is not None
    }
    reconciled: list[dict] = []
    seen: set[tuple] = set()
    covered_catalog: set[int] = set()
    for raw_item in live_items:
        if not isinstance(raw_item, dict):
            raise SearchError("registry search contains an invalid item")
        item = dict(raw_item)
        catalog_item = None
        skill_id = _registry_skill_id(item)
        if skill_id is not None:
            catalog_item = catalog_by_id.get(skill_id)
        if catalog_item is None:
            reference = _registry_reference(item)
            if reference is not None:
                catalog_item = catalog_by_reference.get(reference)
        if catalog_item is not None:
            covered_catalog.add(id(catalog_item))
            # Organization enumeration is authoritative for mutable ownership and
            # visibility. Live search still supplies version, rank, and status.
            for field in ("owner_slug", "skill_name", "skill_id", "owner_id", "visibility"):
                value = catalog_item.get(field)
                if value is not None:
                    item[field] = value
            if not item.get("skill_description"):
                item["skill_description"] = catalog_item.get("skill_description") or ""
        identity = _registry_skill_id(item) or _registry_reference(item)
        key = (identity, item.get("version"))
        if key not in seen:
            seen.add(key)
            reconciled.append(item)
    for item in catalog_items:
        if id(item) in covered_catalog:
            continue
        identity = _registry_skill_id(item) or _registry_reference(item)
        key = (identity, item.get("version"))
        if key not in seen:
            seen.add(key)
            reconciled.append(item)
    return reconciled


def _catalog_snapshot() -> tuple[list[dict], bool]:
    """Authorized Plays from the verified inbox cache, registry-shaped."""

    try:
        from .inbox_cache import read_cache

        cache = read_cache()
    except Exception:  # noqa: BLE001 - the backstop must never break live search
        return [], False
    if cache is None or not isinstance(cache.get("catalog"), list):
        return [], False
    items: list[dict] = []
    for entry in cache["catalog"]:
        if not isinstance(entry, dict):
            continue
        reference = entry.get("reference")
        if not isinstance(reference, str) or "/" not in reference:
            continue
        owner, name = reference.split("/", 1)
        items.append(
            {
                "owner_slug": owner,
                "skill_name": name,
                "skill_description": entry.get("description") or "",
                "visibility": entry.get("visibility"),
                "skill_id": entry.get("skill_id"),
                "owner_id": entry.get("owner_id"),
            }
        )
    return items, cache.get("catalog_complete") is True


def _catalog_items() -> list[dict]:
    """Compatibility helper for callers that need only cached catalog rows."""

    return _catalog_snapshot()[0]


def registry_scope(item: dict) -> str:
    if item.get("visibility") == "public":
        return "remote_public"
    # Search responses can omit visibility. Never infer it from an internal
    # storage path: those paths are not identity or authorization contracts.
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
        "reconciled_from": set(),
        "stale_local_paths": set(),
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
        if not isinstance(name, str):
            raise SearchError("registry search item lacks skill_name")
        if not isinstance(owner, str) or not owner:
            # Some authorized private records intentionally omit a public owner slug.
            # They cannot form a runnable owner/name reference, so ignore only that
            # record instead of discarding valid local, private, and public matches.
            continue
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

    registry_references = set(canonical)
    registry_references_by_fingerprint: dict[str, list[str]] = {}
    for reference, hit in canonical.items():
        registry_references_by_fingerprint.setdefault(
            fingerprint(hit["name"], hit["description"]), []
        ).append(reference)

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
            relocated_matches = registry_references_by_fingerprint.get(
                fingerprint(name, description), []
            )
            if reference not in registry_references and len(relocated_matches) == 1:
                # A local directory preserves the owner at pull time. If the
                # authorized registry now has one unambiguous canonical match,
                # do not let that stale path masquerade as the current identity.
                hit = canonical[relocated_matches[0]]
                hit["reconciled_from"].add(reference)
                hit["stale_local_paths"].add(path_value)
                continue
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
            continue
        hit["sources"].add("local")
        hit["local_paths"].add(item["path"])
        hit["source_ranks"]["local"] = min(rank, hit["source_ranks"].get("local", rank))
        if isinstance(item.get("score"), (int, float)):
            hit["source_scores"]["local"] = max(
                float(item["score"]), hit["source_scores"].get("local", float("-inf"))
            )

    # Legacy local aliases without an owner/name identity are informational only.
    # Current DAG Plays must be addressable by canonical reference; never hand a
    # filesystem path to inspection or execution.
    hits = [*canonical.values()]
    discovery = discovery_queries(normalized_query)
    semantic_query = discovery[-1] if discovery else normalized_query
    query_tokens = set(semantic_query.split())
    for hit in hits:
        searchable = set(normalize_query(f"{hit['name']} {hit['description']}").split())
        coverage = len(query_tokens & searchable) / len(query_tokens) if query_tokens else 0.0
        rank_fusion = sum(1.0 / (60 + rank) for rank in hit["source_ranks"].values())
        hit["combined_score"] = coverage + rank_fusion
        hit["coverage"] = coverage
        # A request naturally carries argument tokens (repo, channel, date) that
        # can never appear in Play metadata, so raw query coverage under-scores
        # parameterized requests. When the query contains the Play's complete
        # name identity, treat the unmatched remainder as arguments, not gaps.
        name_tokens = set(normalize_query(hit["name"]).split())
        name_is_covered = bool(name_tokens) and all(
            _name_token_is_covered(token, query_tokens) for token in name_tokens
        )
        hit["match_classification"] = (
            "full"
            if coverage >= 0.75 or (name_is_covered and coverage >= 0.34)
            else "partial"
            if coverage >= 0.34
            else "uncertain"
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
            if not reference:
                raise SearchError("local DAG Play lacks a canonical owner/name reference")
            exact_reference = reference
            uri = f"https://play.modiqo.ai/{reference}"
            run_command = shlex.join(["rote", "play", "run", reference])
            inspect_command = shlex.join(["rote", "play", "inspect", reference, "--json"])
            hint_kind = "play"
            local_availability = "found"
            execution_resolution = "run_local"
            candidate_reference = reference
        elif reference:
            selected_version = hit["versions_by_scope"].get(primary_scope) or hit["version"]
            exact_reference = f"{reference}@{selected_version}" if selected_version else reference
            uri = f"https://play.modiqo.ai/{reference}"
            run_command = shlex.join(["rote", "play", "run", reference])
            inspect_command = shlex.join(["rote", "play", "inspect", reference, "--json"])
            hint_kind = "play"
            local_availability = "found" if "local" in hit["sources"] else "not_found"
            execution_resolution = "pull_required"
            candidate_reference = reference
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
                    else f"{hit['description']} Registry ownership supersedes the stale local reference(s) {', '.join(sorted(hit['reconciled_from']))}; pulling the canonical Play requires your approval."
                    if hit["reconciled_from"]
                    else f"{hit['description']} Remote {primary_scope.removeprefix('remote_').replace('_', ' ')} match; pulling requires your approval."
                ),
            }
        )
    return output


def _name_token_is_covered(name_token: str, query_tokens: set[str]) -> bool:
    """Accept one bounded typo in a meaningful Play-name token.

    Short tokens remain exact to avoid turning broad words into false matches.
    Longer tokens use a high similarity floor, which covers ordinary
    single-character omissions without making adequacy generally fuzzy.
    """

    if name_token in query_tokens:
        return True
    if len(name_token) < 5:
        return False
    return any(
        len(query_token) >= 4
        and difflib.SequenceMatcher(None, name_token, query_token).ratio() >= 0.88
        for query_token in query_tokens
    )


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
        "source_health": local_payload.get("source_health", {}),
    }
    if args.as_json:
        print(json_text(payload))
    else:
        print(render_markdown(original, normalized, results))
    return 0
