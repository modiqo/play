"""Normalization primitives shared by Play discovery surfaces."""

from __future__ import annotations

import re
import unicodedata


class NormalizationError(ValueError):
    pass


def normalize_query(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    characters: list[str] = []
    for character in decomposed:
        category = unicodedata.category(character)
        if category.startswith(("L", "N")):
            characters.append(character)
        elif category.startswith("M"):
            continue
        else:
            characters.append(" ")
    normalized = " ".join(dict.fromkeys("".join(characters).split()))
    if not normalized:
        raise NormalizationError("query has no searchable letters or numbers after normalization")
    return normalized


def semantic_version_key(value: str | None) -> tuple[tuple[int, int | str], ...]:
    if not value:
        return ()
    parts = re.split(r"[.+-]", value)
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in parts)
