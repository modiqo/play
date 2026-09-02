"""Search local and cached Plays first, then query the registry on a miss."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .commands import CommandError, run_json
from .normalize import (
    NormalizationError,
    normalize_query,
    semantic_version_key,
    token_is_covered,
)
from .render import json_text


SCHEMA = "play.search/v1"
MAX_DESCRIPTION_CHARS = 480
_DISCOVERY_STOP_WORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "at",
    "available",
    "can",
    "conduct",
    "could",
    "do",
    "fetch",
    "find",
    "for",
    "from",
    "get",
    "help",
    "in",
    "into",
    "is",
    "me",
    "month",
    "my",
    "of",
    "on",
    "perform",
    "please",
    "play",
    "plays",
    "related",
    "retrieve",
    "run",
    "that",
    "the",
    "this",
    "to",
    "using",
    "via",
    "want",
    "what",
    "with",
    "would",
    "you",
}
# Concrete request values are Play *arguments*, never outcome vocabulary. A URL,
# path, e-mail, handle, or quoted literal can never appear in Play metadata, so
# leaving it in the query both dilutes coverage scoring and makes the registry's
# AND-of-terms search fail on tokens such as a target host name.
_ARGUMENT_VALUE = re.compile(
    r"""
    (?:[a-z][a-z0-9+.-]*://\S+)            # scheme URLs
    | (?:\bwww\.\S+)                       # bare www hosts
    | (?:\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b) # e-mail addresses
    | (?:(?<![\w/])~?/[\w./+-]+)           # absolute or home-relative paths
    | (?:(?<!\w)@[\w./-]+)                 # @handles and @refs
    | (?:"[^"]*"|'[^']*'|`[^`]*`)          # quoted literals
    | (?:\b\d{4}-\d{2}-\d{2}(?:T[\d:.+Z-]*)?\b) # ISO dates
    """,
    re.IGNORECASE | re.VERBOSE,
)


def strip_argument_values(text: str) -> str:
    """Remove concrete argument values so only outcome vocabulary remains."""

    stripped = _ARGUMENT_VALUE.sub(" ", text)
    return " ".join(stripped.split())


def outcome_query(text: str) -> str:
    """Normalize a request into its searchable outcome vocabulary.

    Falls back to the complete normalized text when stripping argument values
    would leave nothing searchable (for example a bare URL request).
    """

    try:
        return normalize_query(strip_argument_values(text))
    except NormalizationError:
        return normalize_query(text)
_MONTHS = {
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec",
}


class SearchError(CommandError):
    pass


_ORDINAL = re.compile(r"^\d+(?:st|[nr]d|th)$")


def discovery_queries(query: str) -> list[str]:
    """Return bounded broad-to-specific queries without model inference."""

    tokens = query.split()
    stable = [
        token
        for token in tokens
        if token not in _DISCOVERY_STOP_WORDS
        and token not in _MONTHS
        and not token.isdecimal()
        and not _ORDINAL.match(token)
    ]
    broad = " ".join(stable)
    return list(dict.fromkeys(candidate for candidate in (query, broad) if candidate))


def relaxed_registry_query(query: str) -> str | None:
    """Return an OR-joined outcome query for the registry's AND-of-terms search.

    Registry search requires every term to match. Once argument values and stop
    words are gone, joining the remaining outcome tokens with OR lets a Play
    surface when the request phrases the outcome differently from the card;
    coverage scoring in merge_results still decides whether it is adequate.
    """

    broad = discovery_queries(query)[-1]
    tokens = broad.split()
    if len(tokens) < 2:
        return None
    return " OR ".join(tokens)


def search_both(
    query: str | list[str],
    limit: int,
    *,
    flow_root: Path | None = None,
) -> tuple[dict, list]:
    fetch_limit = min(50, max(20, limit * 10))
    query_texts = [query] if isinstance(query, str) else list(query)
    queries = list(
        dict.fromkeys(
            candidate
            for text in query_texts
            for candidate in discovery_queries(text)
        )
    )
    registry_queries = list(
        dict.fromkeys(
            [
                *queries,
                *(
                    relaxed
                    for text in query_texts
                    if (relaxed := relaxed_registry_query(text)) is not None
                ),
            ]
        )
    )
    catalog_items, catalog_complete = _catalog_snapshot()
    local_commands = {}
    for index, candidate in enumerate(queries):
        local_commands[("local", index)] = [
            "rote", "play", "search", candidate, "--limit", str(fetch_limit), "--json"
        ]
    with ThreadPoolExecutor(max_workers=len(local_commands)) as executor:
        pending = {
            key: executor.submit(run_json, command, error_type=SearchError)
            for key, command in local_commands.items()
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
    for index in range(len(queries)):
        local = results.get(("local", index))
        if local is not None:
            flows = _local_search_flows(local)
            if not isinstance(flows, list):
                source_errors[("local", index)] = "local search result has no flows array"
            else:
                for item in flows:
                    key = item.get("path") if isinstance(item, dict) else None
                    if key not in seen_paths:
                        seen_paths.add(key)
                        local_flows.append(item)

    local_payload = {"flows": local_flows}
    resolved_flow_root = flow_root or Path(
        os.environ.get("ROTE_FLOW_DIR", Path.home() / ".rote" / "flows")
    )
    cached_results = merge_results(
        local_payload,
        catalog_items,
        resolved_flow_root,
        limit,
        query_texts,
    )
    cache_hit = any(
        result.get("match_classification") == "full" for result in cached_results
    )

    live_registry_items: list[dict] = []
    if not cache_hit:
        registry_commands = {
            ("registry", index): [
                "rote",
                "play",
                "search",
                candidate,
                "--source",
                "registry",
                "--scope",
                "accessible",
                "--limit",
                str(fetch_limit),
                "--json",
            ]
            for index, candidate in enumerate(registry_queries)
        }
        with ThreadPoolExecutor(max_workers=len(registry_commands)) as executor:
            pending = {
                key: executor.submit(run_json, command, error_type=SearchError)
                for key, command in registry_commands.items()
            }
            for key, future in pending.items():
                try:
                    live_registry_items.extend(_remote_search_items(future.result()))
                except SearchError as error:
                    source_errors[key] = str(error)

    if source_errors and not catalog_complete:
        details = "; ".join(
            f"{source}[{index}]: {message}"
            for (source, index), message in sorted(source_errors.items())
        )
        raise SearchError(
            f"live search was incomplete and no verified complete catalog cache was available: {details}"
        )
    registry_errors = any(source == "registry" for source, _ in source_errors)
    mode = (
        "cached_with_local"
        if cache_hit
        else "cached_fallback"
        if registry_errors
        else "live_after_cache_miss"
    )
    return {
        "flows": local_flows,
        "source_health": {
            "catalog_cache": "complete" if catalog_complete else "unavailable",
            "mode": mode,
            "live_errors": [
                {
                    "source": source,
                    "query": (registry_queries if source == "registry" else queries)[index],
                    "error": message,
                }
                for (source, index), message in sorted(source_errors.items())
            ],
        },
    }, reconcile_registry_items(
        live_registry_items, catalog_items
    )


def _unwrap_result(payload: object) -> object:
    """Unwrap Rote's machine envelope (``{"data": {"result": ...}}``) when present."""

    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        if "result" in payload and isinstance(payload["result"], (dict, list)):
            return payload["result"]
    return payload


def _local_search_flows(payload: object) -> list | None:
    """Return the local flows array, treating a typed empty result as no flows."""

    result = _unwrap_result(payload)
    if isinstance(result, dict):
        flows = result.get("flows")
        if isinstance(flows, list):
            return flows
        fields = result.get("fields")
        if isinstance(fields, dict) and str(fields.get("total", "")).strip() == "0":
            return []
    return None


def _remote_search_items(payload: object) -> list[dict]:
    """Normalize both current and legacy Rote registry search responses."""

    payload = _unwrap_result(payload)
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise SearchError("registry search result has no items array")
    if not isinstance(payload.get("items"), list):
        page = payload.get("page")
        if isinstance(page, dict) and page.get("count") == 0:
            return []
        raise SearchError("registry search result has no items array")
    normalized: list[dict] = []
    for raw_item in payload["items"]:
        if not isinstance(raw_item, dict):
            raise SearchError("registry search contains an invalid item")
        owner = raw_item.get("owner")
        owner_slug = owner.get("slug") if isinstance(owner, dict) else None
        name = raw_item.get("name")
        reference = raw_item.get("reference")
        if (not isinstance(owner_slug, str) or not owner_slug) and isinstance(
            reference, str
        ):
            base_reference = reference.partition("@")[0]
            if "/" in base_reference:
                owner_slug, reference_name = base_reference.split("/", 1)
                if not isinstance(name, str) or not name:
                    name = reference_name
        normalized.append(
            {
                "owner_slug": owner_slug,
                "skill_name": name,
                "skill_description": raw_item.get("description") or "",
                "skill_id": raw_item.get("play_id"),
                "visibility": raw_item.get("visibility"),
                "version": raw_item.get("version"),
                "status": raw_item.get("status"),
                "rank": raw_item.get("rank"),
                "labels": [],
                "tags": raw_item.get("tags") if isinstance(raw_item.get("tags"), list) else [],
                "adapters": (
                    raw_item.get("requires_adapters")
                    if isinstance(raw_item.get("requires_adapters"), list)
                    else []
                ),
            }
        )
    return normalized


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
            for field in (
                "owner_slug",
                "skill_name",
                "skill_id",
                "owner_id",
                "visibility",
                "catalog_tier",
            ):
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
        from .inbox_cache import public_cache_entries, read_cache

        cache = read_cache()
    except Exception:  # noqa: BLE001 - the backstop must never break live search
        return [], False
    if cache is None:
        return [], False
    items: list[dict] = []
    for entry in public_cache_entries(cache):
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
                "catalog_tier": entry.get("catalog_tier"),
                "skill_id": entry.get("skill_id"),
                "owner_id": entry.get("owner_id"),
                "version": entry.get("version"),
                "status": entry.get("status"),
                "labels": entry.get("labels") if isinstance(entry.get("labels"), list) else [],
                "tags": entry.get("tags") if isinstance(entry.get("tags"), list) else [],
                "adapters": (
                    entry.get("adapters")
                    if isinstance(entry.get("adapters"), list)
                    else []
                ),
            }
        )
    return items, cache.get("catalog_complete") is True


def _catalog_items() -> list[dict]:
    """Compatibility helper for callers that need only cached catalog rows."""

    return _catalog_snapshot()[0]


def registry_scope(item: dict) -> str:
    if item.get("catalog_tier") == "public_baseline":
        return "remote_baseline"
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


OWNERSHIP_LABELS = {"yours": "yours", "team": "your team", "community": "community"}
OWNERSHIP_HEADERS = {"yours": "Yours", "team": "Your team", "community": "Community"}


def owner_scope() -> tuple[str | None, set[str]]:
    """Return (profile handle, authorized organization slugs) from the inbox cache.

    Both come from the verified cache the background refresh maintains, so
    search never pays a registry round trip to learn who is asking. A missing
    cache yields no handle and no organizations, which ranks everything as
    community without changing any match classification.
    """

    try:
        from .inbox_cache import read_cache

        cache = read_cache()
    except Exception:  # noqa: BLE001 - identity is a ranking hint, never a gate
        return None, set()
    if not isinstance(cache, dict):
        return None, set()
    handle = cache.get("profile_handle")
    organizations = cache.get("organization_scope")
    return (
        handle if isinstance(handle, str) and handle else None,
        {slug for slug in organizations if isinstance(slug, str)}
        if isinstance(organizations, list)
        else set(),
    )


def classify_ownership(
    reference: str | None, handle: str | None, organizations: set[str]
) -> str:
    owner = (reference or "").partition("/")[0].casefold()
    if not owner:
        return "community"
    if handle and owner == handle.casefold():
        return "yours"
    if owner in {slug.casefold() for slug in organizations}:
        return "team"
    return "community"


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
        "labels": set(),
        "tags": set(),
        "matched_adapters": set(),
    }


def merge_results(
    local_payload: dict,
    registry_payload: list,
    flow_root: Path,
    limit: int,
    normalized_query: str | list[str] = "",
    ownership: tuple[str | None, set[str]] | None = None,
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
        for field in ("labels", "tags"):
            values = item.get(field)
            if isinstance(values, list):
                hit[field].update(
                    value for value in values if isinstance(value, str) and value
                )
        adapters = item.get("adapters")
        if isinstance(adapters, list):
            hit["matched_adapters"].update(
                value for value in adapters if isinstance(value, str) and value
            )
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
    query_texts = (
        [normalized_query] if isinstance(normalized_query, str) else list(normalized_query)
    )
    query_token_sets: list[set[str]] = []
    # Identity tokens keep stop words ("retrieve", "find") because a Play name
    # may legitimately contain one; they are used only to recognise a request
    # that names a Play, never to score outcome coverage.
    identity_token_sets: list[set[str]] = []
    for text in query_texts:
        try:
            outcome = outcome_query(text) if text.strip() else ""
        except NormalizationError:
            outcome = ""
        discovery = discovery_queries(outcome)
        semantic_query = discovery[-1] if discovery else outcome
        tokens = set(semantic_query.split())
        if tokens and tokens not in query_token_sets:
            query_token_sets.append(tokens)
        identity = set(outcome.split())
        if identity and identity not in identity_token_sets:
            identity_token_sets.append(identity)
    if not query_token_sets:
        query_token_sets.append(set())
    handle, organizations = ownership if ownership is not None else owner_scope()
    for hit in hits:
        owner_slug = (hit["reference"] or "").partition("/")[0]
        searchable = set(
            normalize_query(
                " ".join(
                    [
                        hit["name"],
                        owner_slug,
                        hit["description"],
                        *sorted(hit["labels"]),
                        *sorted(hit["tags"]),
                    ]
                )
            ).split()
        )
        # Several phrasings of one request (the harness's intent paraphrase and
        # the user's own words) may be searched together; the best one counts.
        coverage = 0.0
        query_tokens: set[str] = query_token_sets[0]
        uncovered: set[str] = set(query_tokens)
        for candidate_tokens in query_token_sets:
            candidate_uncovered = {
                token
                for token in candidate_tokens
                if not token_is_covered(token, searchable)
            }
            candidate_coverage = (
                (len(candidate_tokens) - len(candidate_uncovered)) / len(candidate_tokens)
                if candidate_tokens
                else 0.0
            )
            if candidate_coverage > coverage or not query_tokens:
                coverage = candidate_coverage
                query_tokens = candidate_tokens
                uncovered = candidate_uncovered
        rank_fusion = sum(1.0 / (60 + rank) for rank in hit["source_ranks"].values())
        hit["combined_score"] = coverage + rank_fusion
        hit["coverage"] = coverage
        # A request naturally carries argument tokens (repo, channel, date) that
        # can never appear in Play metadata, so raw query coverage under-scores
        # parameterized requests. When any phrasing contains the Play's complete
        # name identity, treat the unmatched remainder as arguments, not gaps.
        name_tokens = set(normalize_query(hit["name"]).split())
        name_is_covered = bool(name_tokens) and any(
            all(token_is_covered(token, identity) for token in name_tokens)
            for identity in identity_token_sets
        )
        # "full" is reserved for a request whose every outcome token the card
        # accounts for. A proportional threshold let two words out of three
        # ("summarize last email" -> last-commit-summary) pass as adequate; the
        # dropped word is usually the one that names what the user actually
        # wants, and a full match skips straight to inspect-and-run.
        if query_tokens and not uncovered:
            hit["match_classification"] = "full"
            hit["match_basis"] = "complete"
            hit["argument_terms"] = set()
        elif name_is_covered and coverage >= 0.34:
            hit["match_classification"] = "full"
            hit["match_basis"] = "identity"
            hit["argument_terms"] = set(uncovered)
            uncovered = set()
        elif coverage >= 0.34:
            hit["match_classification"] = "partial"
            hit["match_basis"] = "partial"
            hit["argument_terms"] = set()
        else:
            hit["match_classification"] = "uncertain"
            hit["match_basis"] = "uncertain"
            hit["argument_terms"] = set()
        hit["uncovered_terms"] = uncovered
        adapter_tokens = {
            adapter: set(normalize_query(adapter).split())
            for adapter in hit["matched_adapters"]
        }
        hit["matched_adapters"] = {
            adapter
            for adapter, tokens in adapter_tokens.items()
            if tokens and all(token_is_covered(token, query_tokens) for token in tokens)
        }
        hit["adapter_terms"] = {
            token
            for adapter in hit["matched_adapters"]
            for token in adapter_tokens[adapter]
        }
        hit["primary_scope"] = (
            "local" if "local" in hit["sources"]
            else "remote_private" if "remote_private" in hit["sources"]
            else "remote_public" if "remote_public" in hit["sources"]
            else "remote_baseline"
        )
        hit["ownership"] = classify_ownership(hit["reference"], handle, organizations)
    lexical_full = any(hit["match_classification"] == "full" for hit in hits)
    adapter_matches = [hit for hit in hits if hit["matched_adapters"]]
    if adapter_matches and not lexical_full:
        hits = adapter_matches
        for hit in hits:
            # Naming an adapter ("gmail", "crucible") is a strong association,
            # but it only makes a Play adequate when nothing else in the request
            # is left unexplained. "delete gmail filters" must not run whatever
            # Gmail Play happens to rank first.
            remaining = {
                token
                for token in hit["uncovered_terms"]
                if not token_is_covered(token, hit["adapter_terms"])
            }
            if not remaining:
                hit["match_classification"] = "full"
                hit["match_basis"] = "adapter"
                hit["uncovered_terms"] = set()
            else:
                hit["match_classification"] = "partial"
                hit["match_basis"] = "adapter_partial"
                hit["uncovered_terms"] = remaining
            hit["combined_score"] += 1.0
        best_class = (
            "full"
            if any(hit["match_classification"] == "full" for hit in hits)
            else "partial"
        )
        hits = [hit for hit in hits if hit["match_classification"] == best_class]
    else:
        best_class = "full" if lexical_full else "partial"
        hits = [hit for hit in hits if hit["match_classification"] == best_class]

    class_priority = {"full": 0, "partial": 1, "uncertain": 2}
    scope_priority = {
        "local": 0,
        "remote_private": 1,
        "remote_public": 2,
        "remote_baseline": 3,
    }

    def ownership_tier(hit: dict) -> int:
        # Ownership orders equally adequate Plays only. Classification is
        # decided first and never consults who owns the card, so a community
        # Play with complete coverage still beats the caller's own partial one.
        if hit["primary_scope"] == "local":
            return 0
        if hit["ownership"] == "yours":
            return 1
        if hit["ownership"] == "team":
            return 2 if hit["primary_scope"] == "remote_private" else 3
        return 4 + scope_priority[hit["primary_scope"]]

    hits.sort(key=lambda hit: (
        class_priority[hit["match_classification"]],
        ownership_tier(hit),
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
        adapter_note = (
            f"Matched through adapter(s): {', '.join(sorted(hit['matched_adapters']))}. "
            if hit["matched_adapters"]
            else ""
        )
        if execution_resolution == "run_local":
            selection_description = (
                f"{hit['description']} {adapter_note}Already local; inspect and run "
                "without a pull prompt."
            )
        elif hit["reconciled_from"]:
            selection_description = (
                f"{hit['description']} {adapter_note}Registry ownership supersedes the "
                f"stale local reference(s) {', '.join(sorted(hit['reconciled_from']))}; "
                "pulling the canonical Play requires your approval."
            )
        else:
            selection_description = (
                f"{hit['description']} {adapter_note}Remote "
                f"{primary_scope.removeprefix('remote_').replace('_', ' ')} match; "
                "pulling requires your approval."
            )
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
                "match_basis": hit["match_basis"],
                "uncovered_terms": sorted(hit["uncovered_terms"]),
                "argument_terms": sorted(hit["argument_terms"]),
                "matched_adapters": sorted(hit["matched_adapters"], key=str.casefold),
                "labels": sorted(hit["labels"], key=str.casefold),
                "tags": sorted(hit["tags"], key=str.casefold),
                "primary_scope": primary_scope,
                "ownership": hit["ownership"],
                "uri": uri,
                "run_command": run_command,
                "inspect_command": inspect_command,
                "hint_kind": hint_kind,
                "local_availability": local_availability,
                "execution_resolution": execution_resolution,
                "selection_description": selection_description,
            }
        )
    return output


def render_markdown(
    original: str,
    normalized: str,
    results: list[dict],
    source_health: dict | None = None,
) -> str:
    source_label = (
        "local index + cached authorized Play feed"
        if isinstance(source_health, dict)
        and source_health.get("mode") == "cached_with_local"
        else "local + cached authorized feed + live authorized registry"
    )
    lines = [f"Search: `{normalized}`", "", f"Sources: {source_label}"]
    if original.strip().casefold() != normalized:
        lines.extend(["", f"Normalized from: {original.strip()}"])
    if not results:
        return "\n".join([*lines, "", "No matching Plays found."])
    tiers = [result.get("ownership") for result in results]
    segmented = len({tier for tier in tiers if tier}) > 1
    current_tier = None
    for index, result in enumerate(results, 1):
        source = " + ".join(result["sources"])
        version = f" · v{result['version']}" if result["version"] else ""
        ownership = result.get("ownership")
        if segmented and ownership != current_tier:
            current_tier = ownership
            lines.extend(["", OWNERSHIP_HEADERS.get(ownership, "Community")])
        badges = "".join(
            f" · {value}"
            for value in (result.get("match_classification"), OWNERSHIP_LABELS.get(ownership))
            if value
        )
        lines.extend(
            [
                "",
                f"{index}. **{result['name']}** · {source}{version}{badges} · score {result['score']:.8f}",
                f"   URI: {result['uri']}",
                (
                    "   Local: found; the outcome route runs it immediately after read-only inspection."
                    if result["execution_resolution"] == "run_local"
                    else "   Remote: not local; pull/install requires approval."
                ),
            ]
        )
        lines.append(f"   Next: inspect with `{result['inspect_command']}`")
        if result.get("matched_adapters"):
            lines.append(
                "   Adapter match: " + ", ".join(result["matched_adapters"])
            )
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
        choices.append(
            {
                "reference": reference,
                "label": reference.partition("@")[0],
                "description": (
                    f"{OWNERSHIP_LABELS[result['ownership']]} · {result['selection_description']}"
                    if result.get("ownership") in OWNERSHIP_LABELS
                    else result["selection_description"]
                ),
                "parameters": {},
            }
        )
    return choices


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="+", help="natural-language Play search query")
    parser.add_argument(
        "--also",
        action="append",
        default=[],
        metavar="TEXT",
        help=(
            "another phrasing of the same request (for example the user's original words) "
            "searched alongside the query; the best-matching phrasing scores each Play"
        ),
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    original = " ".join(args.query)
    try:
        normalized = outcome_query(original)
        phrasings = list(
            dict.fromkeys(
                [normalized, *(outcome_query(text) for text in args.also if text.strip())]
            )
        )
        flow_root = Path(
            os.environ.get("ROTE_FLOW_DIR", Path.home() / ".rote" / "flows")
        )
        local_payload, registry_payload = search_both(
            phrasings, args.limit, flow_root=flow_root
        )
        results = merge_results(
            local_payload,
            registry_payload,
            flow_root,
            args.limit,
            phrasings,
        )
    except (SearchError, NormalizationError) as error:
        print(f"play-search: {error}", file=sys.stderr)
        return 1
    payload = {
        "schema": SCHEMA,
        "query": original,
        "normalized_query": normalized,
        "phrasings": phrasings,
        "complete": True,
        "sources": [
            "local",
            "remote_private",
            "remote_public",
            "remote_baseline",
        ],
        "result_refs": [result["reference"] for result in results if result["reference"]],
        "results": results,
        "play_choices": build_play_choices(results),
        "source_health": local_payload.get("source_health", {}),
    }
    if args.as_json:
        print(json_text(payload))
    else:
        print(
            render_markdown(
                original,
                normalized,
                results,
                local_payload.get("source_health"),
            )
        )
    return 0
