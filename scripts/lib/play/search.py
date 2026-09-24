"""Discover published Plays through the shared relevance Worker."""

from __future__ import annotations

import argparse
import re
import shlex
import sys

from .commands import CommandError
from .search_transport import request_search
from .elicitation import clip_choice_description
from .normalize import (
    NormalizationError,
    normalize_query,
)
from .render import json_text


SCHEMA = "play.search/v1"
_DISCOVERY_STOP_WORDS = {
    "a",
    "about",
    "also",
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
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
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


# A request that names two separable outcomes ("today's meetings and the
# weather") must be searched once per outcome. Scoring the blended phrase ranks
# Plays that describe the *combination* (briefings, digests) above the Plays
# that each deliver one half, and the halves then never surface at all.
_OUTCOME_SEPARATOR = re.compile(
    r"""
    \s*(?:
        ;
        | ,\s*(?:and\s+)?(?:also\s+)?(?:then\s+)?
        | \b(?:and\s+also|and\s+then|as\s+well\s+as|along\s+with|together\s+with)\b
        | \b(?:and|plus|then|also)\b
    )\s*
    """,
    re.IGNORECASE | re.VERBOSE,
)
# The minimum outcome vocabulary a segment must keep to stand on its own. A
# one-word remainder ("... and cost") would make any Play that mentions the word
# a full match, so it never becomes a separately searched outcome.
MIN_SUB_OUTCOME_TOKENS = 2


def outcome_tokens(text: str) -> list[str]:
    """Return the stable outcome vocabulary of one phrasing, in order."""

    try:
        outcome = outcome_query(text) if text.strip() else ""
    except NormalizationError:
        return []
    discovery = discovery_queries(outcome)
    semantic = discovery[-1] if discovery else outcome
    return [token for token in semantic.split() if len(token) > 1]


def separable_outcomes(text: str) -> list[str]:
    """Split one phrasing into separately searchable outcomes.

    Returns the original phrasing alone unless every conjunction-separated
    segment keeps at least MIN_SUB_OUTCOME_TOKENS outcome tokens and no
    segment's vocabulary is contained in another's. Argument values are removed
    first so a URL or path containing a separator cannot split a request.
    """

    stripped = strip_argument_values(text)
    segments = [
        segment for segment in _OUTCOME_SEPARATOR.split(stripped) if segment.strip()
    ]
    if len(segments) < 2:
        return [text]
    token_sets = [set(outcome_tokens(segment)) for segment in segments]
    if any(len(tokens) < MIN_SUB_OUTCOME_TOKENS for tokens in token_sets):
        return [text]
    kept: list[tuple[str, set[str]]] = []
    for segment, tokens in zip(segments, token_sets):
        if any(tokens <= other for _, other in kept):
            continue
        kept = [
            (other_segment, other)
            for other_segment, other in kept
            if not other <= tokens
        ]
        kept.append((segment.strip(), tokens))
    return [segment for segment, _ in kept] if len(kept) >= 2 else [text]


def outcome_groups(phrasings: list[str]) -> list[list[str]]:
    """Group the separable outcomes of several phrasings of one request.

    Each phrasing (the harness's intent paraphrase and the user's own words) is
    split on its own; segments from different phrasings that share outcome
    vocabulary describe the same sub-outcome and are searched together, so the
    best phrasing scores each Play exactly as it does for an atomic request.
    Returns fewer than two groups when the request is atomic.
    """

    segments: list[tuple[str, set[str]]] = []
    for phrasing in phrasings:
        for segment in separable_outcomes(phrasing):
            tokens = set(outcome_tokens(segment))
            if tokens and (segment, tokens) not in segments:
                segments.append((segment, tokens))
    parent = list(range(len(segments)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left in range(len(segments)):
        for right in range(left + 1, len(segments)):
            if segments[left][1] & segments[right][1]:
                parent[find(left)] = find(right)
    grouped: dict[int, list[str]] = {}
    for index, (segment, _) in enumerate(segments):
        grouped.setdefault(find(index), []).append(segment)
    groups = list(grouped.values())
    if len(groups) < 2:
        return []
    return groups


# This redaction preserves quoted task constraints; lexical normalization above
# remains solely for authoring tag hints and outcome segmentation.
_SENSITIVE_ARGUMENT = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://\S+|\bwww\.\S+|\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b|(?<![\w/])~?/[\w./+-]+|(?<!\w)@[\w./-]+|\b\d{4}-\d{2}-\d{2}(?:T[\d:.+Z-]*)?)",
    re.I,
)
_SECRET = re.compile(
    r"\b(?:bearer\s+\S+|(?:api[_-]?key|token|password|secret)\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|\S+))",
    re.I,
)
_REFERENCE = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+@[A-Za-z0-9_.+-]+$")


def relevance_query(text: str) -> str:
    query = " ".join(
        _SENSITIVE_ARGUMENT.sub("[argument]", _SECRET.sub("[credential]", text)).split()
    )
    if not 3 <= len(query) <= 400:
        raise SearchError(
            "Use 3–400 characters describing the task and its constraints; shorten long requests without dropping exclusions."
        )
    return query


def _unwrap_worker(payload: object) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"].get("result", payload)
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "modiqo.play-search.v1"
    ):
        raise SearchError(
            "Shared search returned an invalid contract; no local fallback was used."
        )
    return payload


def _validate_worker(body: dict, public: bool, org: str | None) -> None:
    registry = body.get("registry")
    if (
        registry not in ("production", "staging")
        or body.get("mode") not in ("judged", "degraded")
        or type(body.get("complete")) is not bool
    ):
        raise SearchError("Invalid shared search status.")
    groups = body.get("groups")
    if (
        not isinstance(groups, list)
        or len(groups) > 22
        or not isinstance(body.get("omitted_groups"), list)
    ):
        raise SearchError("Invalid shared search groups.")
    kinds = set()
    ids = set()
    seen = set()
    origin = (
        "https://play.modiqo.ai/"
        if registry == "production"
        else "https://play.stg.modiqo.ai/"
    )
    for group in groups:
        if not isinstance(group, dict) or group.get("kind") not in (
            "community",
            "personal",
            "organization",
        ):
            raise SearchError("Invalid shared search scope.")
        kind = group["kind"]
        identity = (kind, group.get("id"))
        if (
            not isinstance(group.get("id"), str)
            or identity in ids
            or not isinstance(group.get("label"), str)
        ):
            raise SearchError("Invalid shared search group identity.")
        ids.add(identity)
        kinds.add(kind)
        if (
            public
            and kind != "community"
            or org
            and (kind != "organization" or group.get("owner_slug") != org)
        ):
            raise SearchError("Shared search returned an unexpected scope.")
        retrieval = group.get("retrieval")
        if not isinstance(retrieval, dict) or retrieval.get("status") not in (
            "ok",
            "partial",
            "unavailable",
        ):
            raise SearchError("Invalid retrieval status.")
        for key, statuses in [
            ("matches", ("direct", "partial")),
            ("uncertain", ("uncertain", "unverified")),
        ]:
            items = group.get(key)
            if not isinstance(items, list) or len(items) > 12:
                raise SearchError("Invalid bounded search results.")
            for item in items:
                if not isinstance(item, dict):
                    raise SearchError("Invalid search candidate.")
                reference = item.get("reference")
                relevance = item.get("relevance")
                if (
                    not isinstance(reference, str)
                    or not _REFERENCE.fullmatch(reference)
                    or item.get("url") != origin + reference
                    or reference in seen
                ):
                    raise SearchError("Invalid or duplicate published Play identity.")
                seen.add(reference)
                if not all(
                    isinstance(item.get(field), str)
                    for field in ["name", "description", "version", "owner_slug"]
                ):
                    raise SearchError("Invalid published Play metadata.")
                if (
                    reference
                    != f"{item['owner_slug']}/{item['name']}@{item['version']}"
                ):
                    raise SearchError("Inconsistent published Play identity.")
                if (
                    item.get("visibility") not in ("public", "private")
                    or kind == "community"
                    and item["visibility"] != "public"
                ):
                    raise SearchError("Invalid Play visibility.")
                if kind != "community" and item["owner_slug"] != group.get(
                    "owner_slug"
                ):
                    raise SearchError("Published Play belongs to another search group.")
                if (
                    not isinstance(relevance, dict)
                    or relevance.get("status") not in statuses
                ):
                    raise SearchError("Invalid relevance judgment.")
    if not org and "community" not in kinds:
        raise SearchError("Shared search omitted the community scope.")
    if org and len(groups) != 1:
        raise SearchError("Shared search omitted the requested organization.")


def _result(item: dict, group: dict) -> dict:
    status = item["relevance"]["status"]
    classification = {
        "direct": "full",
        "partial": "partial",
        "uncertain": "uncertain",
        "unverified": "uncertain",
    }[status]
    scope = "remote_public" if item["visibility"] == "public" else "remote_private"
    ownership = {"personal": "yours", "organization": "team", "community": "community"}[
        group["kind"]
    ]
    probability = item["relevance"].get("probability", 0)
    probability = (
        float(probability)
        if isinstance(probability, (int, float)) and 0 <= probability <= 1
        else 0.0
    )
    return {
        "name": item["name"],
        "description": item["description"],
        "reference": item["reference"],
        "exact_reference": item["reference"],
        "version": item["version"],
        "status": "published",
        "sources": [scope],
        "score": probability,
        "coverage": probability,
        "match_classification": classification,
        "match_basis": "jev",
        "relevance_status": status,
        "uncovered_terms": []
        if status == "direct"
        else ["Whole-request fit is not established"],
        "argument_terms": [],
        "matched_adapters": [],
        "labels": [],
        "tags": [],
        "primary_scope": scope,
        "ownership": ownership,
        "uri": item["url"],
        "run_command": shlex.join(["rote", "play", "run", item["reference"]]),
        "inspect_command": shlex.join(
            ["rote", "play", "inspect", item["reference"], "--json"]
        ),
        "hint_kind": "play",
        "local_availability": "unknown",
        "execution_resolution": "inspect_required",
        "selection_description": f"{status} · {item['description']} Inspect the published version before use.",
        "group_id": group["id"],
        "group_label": group["label"],
        "group_kind": group["kind"],
    }


def search_published(
    query: str,
    limit: int = 5,
    *,
    public: bool = False,
    org: str | None = None,
    timeout_seconds: float = 25.0,
) -> dict:
    query = relevance_query(query)
    if not 1 <= limit <= 12:
        raise SearchError("Shared search supports --limit 1–12 per group.")
    if public and org:
        raise SearchError("Organization search requires accessible scope.")
    try:
        body = _unwrap_worker(request_search(query, public=public, org=org, limit=limit, timeout_seconds=timeout_seconds))
    except CommandError as error:
        raise SearchError(str(error)) from None
    _validate_worker(body, public, org)
    results = [
        _result(item, group)
        for group in body["groups"]
        for key in ["matches", "uncertain"]
        for item in group[key]
    ]
    results.sort(
        key=lambda item: (
            {"full": 0, "partial": 1, "uncertain": 2}[item["match_classification"]],
            {"yours": 0, "team": 1, "community": 2}[item["ownership"]],
            -item["score"],
            item["exact_reference"],
        )
    )
    complete = (
        body["complete"]
        and body["mode"] == "judged"
        and not body["omitted_groups"]
        and all(
            group.get("judgment_complete") is True
            and group.get("display_truncated") is False
            and group["retrieval"].get("status") == "ok"
            and group["retrieval"].get("truncated") is False
            for group in body["groups"]
        )
    )
    health = {
        "mode": body["mode"],
        "registry": body["registry"],
        "complete": complete,
        "policy_version": body.get("policy_version", ""),
        "omitted_groups": body["omitted_groups"],
        "groups": [
            {
                key: group.get(key)
                for key in [
                    "kind",
                    "id",
                    "label",
                    "retrieval",
                    "judgment_complete",
                    "display_truncated",
                ]
            }
            for group in body["groups"]
        ],
    }
    return {
        "schema": SCHEMA,
        "query": query,
        "normalized_query": query,
        "complete": complete,
        "sources": ["shared_worker"],
        "result_refs": [item["reference"] for item in results],
        "results": results,
        "play_choices": build_play_choices(results),
        "sub_outcomes": [],
        "source_health": health,
    }


def build_play_choices(results: list[dict]) -> list[dict]:
    return [
        {
            "reference": item["exact_reference"],
            "label": item["reference"].partition("@")[0],
            "description": clip_choice_description(item["selection_description"]),
            "parameters": {},
        }
        for item in results
    ]


def render_markdown(
    original: str,
    normalized: str,
    results: list[dict],
    source_health: dict | None = None,
    sub_outcomes: list[dict] | None = None,
) -> str:
    health = source_health or {}
    lines = [
        f"Search: {normalized}",
        "",
        "Sources: published Plays · shared search Worker",
    ]
    if health.get("complete") is not True:
        lines += [
            "",
            "Search is incomplete. Missing results do not establish that no suitable Play exists.",
        ]
    for uncertain in [False, True]:
        selected = [
            item
            for item in results
            if (item.get("match_classification") == "uncertain") == uncertain
        ]
        if not selected:
            continue
        lines += [
            "",
            "Possible matches — relevance uncertain or unverified"
            if uncertain
            else "Matches",
        ]
        groups: dict[tuple[str, str], list[dict]] = {}
        for item in selected:
            groups.setdefault(
                (item.get("group_id", ""), item.get("group_label", "Published Plays")),
                [],
            ).append(item)
        for (_, label), items in groups.items():
            lines += ["", label]
            for item in items:
                lines += [
                    f"- {item['name']} · {item.get('relevance_status', item['match_classification'])}",
                    f"  {item['uri']}",
                    f"  Inspect: `{item['inspect_command']}`",
                ]
    if not results:
        lines += [
            "",
            "No matches in the results checked."
            if health.get("complete") is not True
            else "No matching published Plays found.",
        ]
    for outcome in sub_outcomes or []:
        lines += ["", f"Part: {outcome['outcome']} · {outcome['classification']}"]
    return "\n".join(lines)


def search_request(
    original: str,
    limit: int = 5,
    *,
    decompose: bool = False,
    public: bool = False,
    org: str | None = None,
) -> dict:
    query = relevance_query(original)
    payload = search_published(query, limit, public=public, org=org)
    if decompose:
        segments = separable_outcomes(query)
        if len(segments) > 1:
            # Every sub-query retains the whole request, including exclusions.
            if len(segments) > 3:
                payload["complete"] = False
            for segment in segments[:3]:
                subquery = f"Request: {query}\nFind a Play for this part, respecting the request constraints: {segment}"
                try:
                    sub = search_published(subquery, limit, public=public, org=org)
                except (SearchError, OSError):
                    sub = {"complete": False, "results": [], "result_refs": []}
                payload["complete"] = payload["complete"] and sub["complete"]
                top = sub["results"][0] if sub["results"] else None
                payload["sub_outcomes"].append(
                    {
                        "outcome": segment,
                        "complete": sub["complete"],
                        "phrasings": [subquery],
                        "query": subquery,
                        "result_refs": sub["result_refs"],
                        "results": sub["results"],
                        "classification": top["match_classification"]
                        if top
                        else "none",
                        "reference": top["reference"] if top else None,
                        "uncovered_terms": top["uncovered_terms"] if top else [segment],
                    }
                )
    payload["source_health"]["complete"] = payload["complete"]
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="+")
    parser.add_argument(
        "--also",
        action="append",
        default=[],
        help="Original user wording; takes precedence over an intent paraphrase.",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--public",
        action="store_true",
        help="Search only published community Plays without identity.",
    )
    parser.add_argument("--org", help="Search one currently accessible organization.")
    parser.add_argument("--decompose", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    original = args.also[-1] if args.also else " ".join(args.query)
    try:
        payload = search_request(
            original,
            args.limit,
            decompose=args.decompose,
            public=args.public,
            org=args.org,
        )
    except (SearchError, NormalizationError, OSError) as error:
        print(f"play-search: {error}", file=sys.stderr)
        return 1
    print(
        json_text(payload)
        if args.as_json
        else render_markdown(
            original,
            payload["query"],
            payload["results"],
            payload["source_health"],
            payload["sub_outcomes"],
        )
    )
    return 0
