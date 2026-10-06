"""Idempotent local setup of Play-owned owner state.

Installers call this after placing Play: it seeds the private routing policy,
journal settings, and Journey model assets. It never touches launchers, skill
links, plugins, hooks, authentication, or timers; those belong to the installer.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Literal

import yaml

from . import routing
from .journal_settings import ensure_journal_settings
from .journey_model_telemetry import ModelTelemetryError, ensure_model_assets


SCHEMA = "play.setup/v1"
StepStatus = Literal["created", "current", "error"]


@dataclass(frozen=True)
class SetupStep:
    name: str
    status: StepStatus
    detail: str


def _routing_policy() -> SetupStep:
    path = routing.user_policy_path()
    if routing.initialize(path, private=True):
        return SetupStep("routing_policy", "created", f"created empty routing policy {path}")
    routing.load_policy(path)
    return SetupStep("routing_policy", "current", f"kept existing routing policy {path}")


def _journal_settings() -> SetupStep:
    settings, changed = ensure_journal_settings()
    exploration = settings["exploration"]
    exploration_state = (
        f"every {exploration['interval_steps']} steps"
        if settings["enabled"] and exploration["enabled"]
        else "off"
    )
    recall_state = "on" if settings["enabled"] and settings["recall"]["enabled"] else "off"
    summary = f"exploration journal {exploration_state}; recall history {recall_state}"
    if changed:
        return SetupStep("journal_settings", "created", f"wrote journal settings: {summary}")
    return SetupStep("journal_settings", "current", f"journal settings current: {summary}")


def _model_assets() -> SetupStep:
    assets = ensure_model_assets()
    changes = []
    if assets["config_created"]:
        changes.append(f"created {assets['config']}")
    if assets["catalog_refreshed"]:
        changes.append(f"refreshed {assets['catalog']}")
    if changes:
        return SetupStep("model_assets", "created", "; ".join(changes))
    return SetupStep(
        "model_assets", "current", f"kept {assets['config']} and {assets['catalog']}"
    )


STEPS: tuple[tuple[str, Callable[[], SetupStep]], ...] = (
    ("routing_policy", _routing_policy),
    ("journal_settings", _journal_settings),
    ("model_assets", _model_assets),
)


def run_setup() -> list[SetupStep]:
    results: list[SetupStep] = []
    for name, step in STEPS:
        try:
            results.append(step())
        except (OSError, ValueError, yaml.YAMLError, ModelTelemetryError) as error:
            results.append(SetupStep(name, "error", str(error)))
    return results


def render(steps: Sequence[SetupStep]) -> str:
    symbols = {"created": "+", "current": "=", "error": "!"}
    lines = ["Play local setup"]
    lines.extend(f"  {symbols[step.status]} {step.name}: {step.detail}" for step in steps)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="play-setup", description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help=f"print one {SCHEMA} JSON object"
    )
    arguments = parser.parse_args(argv)
    steps = run_setup()
    if arguments.json:
        print(json.dumps({"schema": SCHEMA, "steps": [asdict(step) for step in steps]}))
    else:
        print(render(steps))
    return 1 if any(step.status == "error" for step in steps) else 0
