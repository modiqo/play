"""Typed command and JSON helpers shared by Play entrypoints."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar


class CommandError(RuntimeError):
    """A command failed or returned an invalid primary payload."""


ErrorT = TypeVar("ErrorT", bound=CommandError)

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SECTION_LINE = re.compile(r"(?m)^@@[a-z0-9_:.-]+[ \t]*$")


def parse_rote_json(output: str) -> Any:
    """Parse JSON from either machine mode or Rote's typed result envelope.

    Rote normally emits only JSON when ``--json`` is honored. Harness wrappers
    and older/newer CLI surfaces can instead preserve the structured
    ``@@status``/``@@result`` envelope. Both registry catalog reads and Play
    search use this one parser so their wire compatibility cannot drift.
    """

    stripped = output.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as direct_error:
        clean = _ANSI_ESCAPE.sub("", output)
        sections = list(_SECTION_LINE.finditer(clean))
        result = next(
            (match for match in sections if match.group(0).strip() == "@@result"),
            None,
        )
        if result is None:
            raise direct_error
        end = next(
            (match.start() for match in sections if match.start() > result.end()),
            len(clean),
        )
        payload = clean[result.end() : end].strip()
        if not payload:
            raise direct_error
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            raise direct_error


def run_text(
    command: Sequence[str],
    *,
    error_type: type[ErrorT] = CommandError,
    environment: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
    working_directory: str | Path | None = None,
) -> str:
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
            cwd=working_directory,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise error_type(f"{label} timed out after {timeout_seconds:g}s") from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown command error"
        raise error_type(f"{label} failed: {detail}")
    return result.stdout


def run_json(
    command: Sequence[str],
    *,
    error_type: type[ErrorT] = CommandError,
    environment: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
    working_directory: str | Path | None = None,
) -> Any:
    output = run_text(
        command,
        error_type=error_type,
        environment=environment,
        timeout_seconds=timeout_seconds,
        working_directory=working_directory,
    )
    label = " ".join(command[:4])
    try:
        return parse_rote_json(output)
    except json.JSONDecodeError as error:
        raise error_type(f"{label} returned malformed JSON") from error


def run_rote_json(
    *arguments: str,
    error_type: type[ErrorT] = CommandError,
    timeout_seconds: float | None = None,
    working_directory: str | Path | None = None,
) -> Any:
    return run_json(
        ["rote", *arguments],
        error_type=error_type,
        timeout_seconds=timeout_seconds,
        working_directory=working_directory,
    )
