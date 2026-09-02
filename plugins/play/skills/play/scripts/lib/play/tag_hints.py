"""Suggest discoverability tags from the request that created a Play.

A Play is found by token coverage over its name, description, labels, and
tags. When the originating request carries outcome words the card does not
cover, the Play cannot be found by the very request it was built for. This
tool reports those words so they can become tags before release.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import yaml

from .normalize import NormalizationError, normalize_query, token_is_covered
from .render import json_text
from .search import discovery_queries, outcome_query

SCHEMA = "play.tag-hints/v1"
_FRONTMATTER = re.compile(r"@rote-frontmatter\s*\n(.*?)\*/", re.DOTALL)


class TagHintError(ValueError):
    pass


def read_card(play_path: Path) -> dict[str, Any]:
    """Return name, description, and tags from a Play's frontmatter comment."""

    try:
        text = play_path.read_text(encoding="utf-8")
    except OSError as error:
        raise TagHintError(f"cannot read {play_path}: {error}") from error
    match = _FRONTMATTER.search(text)
    if match is None:
        raise TagHintError(f"{play_path} has no @rote-frontmatter block")
    lines = []
    for raw in match.group(1).splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("*"):
            stripped = stripped[1:]
            if stripped.startswith(" "):
                stripped = stripped[1:]
        lines.append(stripped)
    body = "\n".join(lines)
    if body.lstrip().startswith("---"):
        body = body.lstrip()[3:]
    try:
        # The block opens and closes with "---"; only the first document is the card.
        data = next(iter(yaml.safe_load_all(body)), None) or {}
    except yaml.YAMLError as error:
        raise TagHintError(f"{play_path} frontmatter is not valid YAML: {error}") from error
    if not isinstance(data, dict):
        raise TagHintError(f"{play_path} frontmatter is not a mapping")
    metadata_value = data.get("metadata")
    metadata: dict[str, Any] = metadata_value if isinstance(metadata_value, dict) else {}
    discoverability_value = metadata.get("discoverability")
    discoverability: dict[str, Any] = (
        discoverability_value if isinstance(discoverability_value, dict) else {}
    )
    tags = discoverability.get("tags")
    return {
        "name": str(data.get("name") or ""),
        "description": str(data.get("description") or ""),
        "tags": [str(tag) for tag in tags] if isinstance(tags, list) else [],
    }


def suggest_tags(
    requests: Sequence[str], name: str, description: str, tags: Sequence[str]
) -> dict[str, Any]:
    """Return the outcome words of each request the card does not cover."""

    searchable = set(normalize_query(" ".join([name, description, *tags]) or "-").split())
    uncovered: list[str] = []
    considered: list[str] = []
    for text in requests:
        if not text.strip():
            continue
        try:
            outcome = outcome_query(text)
        except NormalizationError:
            continue
        discovery = discovery_queries(outcome)
        semantic = discovery[-1] if discovery else outcome
        for token in semantic.split():
            if token not in considered:
                considered.append(token)
            if not token_is_covered(token, searchable) and token not in uncovered:
                uncovered.append(token)
    return {
        "schema": SCHEMA,
        "ok": True,
        "card": {"name": name, "description": description, "tags": list(tags)},
        "outcome_terms": considered,
        "uncovered_terms": uncovered,
        "suggested_tags": uncovered,
        "discoverable_by_request": not uncovered and bool(considered),
    }


def render_markdown(report: dict[str, Any]) -> str:
    if report["suggested_tags"]:
        return "\n".join(
            [
                "Suggested discoverability tags (outcome words the card does not cover):",
                *(f"- {tag}" for tag in report["suggested_tags"]),
                "",
                "Add them under metadata.discoverability.tags before release.",
            ]
        )
    if report["outcome_terms"]:
        return "The card already covers every outcome word of the request."
    return "The request carries no outcome words to compare."


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", action="append", default=[], required=True)
    parser.add_argument("--play", type=Path, help="path to the Play's main.ts")
    parser.add_argument("--name", default="")
    parser.add_argument("--description", default="")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(arguments)
    try:
        if args.play is not None:
            card = read_card(args.play)
        else:
            card = {"name": args.name, "description": args.description, "tags": args.tag}
        report = suggest_tags(args.request, card["name"], card["description"], card["tags"])
    except TagHintError as error:
        print(f"play-tag-hints: {error}", file=sys.stderr)
        return 1
    print(json_text(report) if args.as_json else render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
