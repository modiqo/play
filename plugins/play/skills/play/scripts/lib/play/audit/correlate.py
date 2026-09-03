"""Cross-input facts: things no single extractor can see on its own."""

from __future__ import annotations

from typing import Any

from .bodies import BodyAnalysis
from .model import Collected, Location
from .package import Package
from .rules import rule
from .steps import StepAnalysis


def correlate(package: Package, steps: StepAnalysis, bodies: BodyAnalysis) -> Collected:
    out = Collected()
    front = package.frontmatter
    if front.error:
        return out

    if not front.parameters_top_level and isinstance(front.metadata.get("parameters"), list):
        out.add(rule("PARAMETERS_UNDER_METADATA").finding(Location(path="metadata.parameters")))

    process_commands = steps.commands_run
    if process_commands and not package.deps_present:
        out.add(rule("DEPS_TOML_MISSING").finding(Location(file="deps.toml"), commands=", ".join(sorted(process_commands))))

    if package.deps_present and not package.deps_error:
        for command, tool in sorted(package.tools.items()):
            if tool.required and command not in process_commands and command not in _spawned(bodies) \
                    and command not in bodies.shell_commands:
                out.add(rule("TOOL_DECLARED_UNUSED").finding(Location(file="deps.toml"), command=command))

    read = steps.params_read | bodies.params_read
    for param in front.parameter_names:
        if param not in read and param.replace("-", "_") not in read:
            out.add(rule("PARAM_UNREFERENCED").finding(Location(path=f"parameters.{param}"), param=param))

    manifest = package.manifest
    if manifest is not None:
        _manifest_drift(out, front_parameters=front.parameter_names, front_steps=sorted(front.steps), manifest=manifest)
    return out


def _spawned(bodies: BodyAnalysis) -> set[str]:
    return {spawn.command for spawn in bodies.spawns if spawn.command}


def _manifest_drift(out: Collected, *, front_parameters: list[str], front_steps: list[str], manifest: dict[str, Any]) -> None:
    raw_params = manifest.get("parameters")
    if raw_params is None and isinstance(manifest.get("metadata"), dict):
        raw_params = manifest["metadata"].get("parameters")
    if isinstance(raw_params, list):
        manifest_params = sorted(str(p.get("name")) for p in raw_params if isinstance(p, dict) and "name" in p)
        if manifest_params != sorted(front_parameters):
            out.add(rule("MANIFEST_DRIFT").finding(
                Location(file="manifest.json"), field="parameters",
                detail=f"frontmatter {sorted(front_parameters)} vs manifest {manifest_params}"))
    raw_steps = manifest.get("steps")
    if isinstance(raw_steps, dict):
        manifest_steps = sorted(str(name) for name in raw_steps)
        if manifest_steps != front_steps:
            out.add(rule("MANIFEST_DRIFT").finding(
                Location(file="manifest.json"), field="steps",
                detail=f"frontmatter {front_steps} vs manifest {manifest_steps}"))
