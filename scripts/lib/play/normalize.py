"""Normalization primitives shared by Play discovery surfaces."""

from __future__ import annotations

import difflib
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


def token_is_covered(expected: str, actual_tokens: set[str]) -> bool:
    """Return whether a meaningful token is present, allowing one bounded typo.

    Short tokens remain exact so common words cannot become broad fuzzy matches.
    The high similarity floor covers ordinary single-character omissions in
    longer identity tokens without making general catalog text fuzzy.
    """

    if expected in actual_tokens:
        return True
    if len(expected) < 5:
        return False
    return any(
        len(actual) >= 4
        and (
            difflib.SequenceMatcher(None, expected, actual).ratio() >= 0.88
            or _shares_stem(expected, actual)
        )
        for actual in actual_tokens
    )


def _shares_stem(left: str, right: str) -> bool:
    """Return whether two long tokens are inflections of one word.

    ``assess``/``assessment``, ``summary``/``summarize`` and ``receipt``/``receipts``
    describe the same outcome. A shared prefix that is at least five characters
    and covers most of the shorter token counts; unrelated words that merely
    start alike (``inter``/``internal``) fail the ratio.
    """

    if len(left) < 5 or len(right) < 5:
        return False
    shared = 0
    for a, b in zip(left, right):
        if a != b:
            break
        shared += 1
    shorter = min(len(left), len(right))
    return shared >= 5 and shared >= 0.75 * shorter
