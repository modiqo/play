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
    timeout_seconds: float | None = None,
) -> Any:
    effective_environment = os.environ.copy()
    effective_environment.setdefault("ROTE_NO_HINTS", "1")
    if environment:
        effective_environment.update(environment)
    label = " ".join(command[:4])
    if timeout_seconds is None:
        raw_timeout = effective_environment.get("PLAY_COMMAND_TIMEOUT_SECONDS", "30")
        try:
            timeout_seconds = float(raw_timeout)
        except ValueError as error:
            raise error_type("PLAY_COMMAND_TIMEOUT_SECONDS must be a number") from error
    if timeout_seconds <= 0:
        raise error_type("command timeout must be greater than zero")
    try:
        result = subprocess.run(
            list(command),
            text=True,
            capture_output=True,
            env=effective_environment,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise error_type(f"{label} timed out after {timeout_seconds:g}s") from error
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
    timeout_seconds: float | None = None,
) -> Any:
    return run_json(
        ["rote", *arguments],
        error_type=error_type,
        timeout_seconds=timeout_seconds,
    )
