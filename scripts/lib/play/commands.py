"""Typed command and JSON helpers shared by Play entrypoints."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Sequence
from typing import Any, TypeVar


class CommandError(RuntimeError):
    """A command failed or returned an invalid primary payload."""


ErrorT = TypeVar("ErrorT", bound=CommandError)


def run_json(
    command: Sequence[str],
    *,
    error_type: type[ErrorT] = CommandError,
    environment: dict[str, str] | None = None,
) -> Any:
    effective_environment = os.environ.copy()
    effective_environment.setdefault("rote_NO_HINTS", "1")
    if environment:
        effective_environment.update(environment)
    result = subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        env=effective_environment,
        check=False,
    )
    label = " ".join(command[:4])
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown command error"
        raise error_type(f"{label} failed: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise error_type(f"{label} returned malformed JSON") from error


def run_rote_json(
    *arguments: str,
    error_type: type[ErrorT] = CommandError,
) -> Any:
    return run_json(["rote", *arguments], error_type=error_type)
