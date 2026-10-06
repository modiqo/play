"""Canonical harness capabilities for runtime handoffs and preflight."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping


ExecutableResolver = Callable[[str], str | None]


@dataclass(frozen=True)
class HarnessSpec:
    """Describe one harness without coupling it to installer presentation."""

    id: str
    label: str
    command: str
    config_env: str
    default_home: str
    skill_sources: tuple[str, ...]
    start_command: tuple[str, ...]
    play_entry: str
    prompt_surface: str


HARNESS_SPECS = (
    HarnessSpec(
        id="codex",
        label="Codex",
        command="codex",
        config_env="CODEX_HOME",
        default_home=".codex",
        skill_sources=("native",),
        start_command=("codex",),
        play_entry="$play",
        prompt_surface="request_user_input",
    ),
    HarnessSpec(
        id="claude",
        label="Claude Code",
        command="claude",
        config_env="CLAUDE_CONFIG_DIR",
        default_home=".claude",
        skill_sources=("native",),
        start_command=("claude",),
        play_entry="/play",
        prompt_surface="askquestion",
    ),
    HarnessSpec(
        id="kimi",
        label="Kimi",
        command="kimi",
        config_env="KIMI_CONFIG_DIR",
        default_home=".kimi",
        skill_sources=("native", "agents-config", "agents"),
        start_command=("kimi",),
        play_entry="/skill:play",
        prompt_surface="askquestion",
    ),
    HarnessSpec(
        id="cursor",
        label="Cursor",
        command="cursor",
        config_env="CURSOR_CONFIG_DIR",
        default_home=".cursor",
        skill_sources=("native", "agents"),
        start_command=("cursor",),
        play_entry="/play",
        prompt_surface="structured_elicitation",
    ),
    HarnessSpec(
        id="hermes",
        label="Hermes Agent",
        command="hermes",
        config_env="HERMES_HOME",
        default_home=".hermes",
        skill_sources=("native",),
        start_command=("hermes",),
        play_entry="/play",
        prompt_surface="structured_elicitation",
    ),
    HarnessSpec(
        id="opencode",
        label="OpenCode",
        command="opencode",
        config_env="OPENCODE_CONFIG_DIR",
        default_home=".config/opencode",
        skill_sources=("native", "agents"),
        start_command=("opencode",),
        play_entry="/play",
        prompt_surface="structured_elicitation",
    ),
    HarnessSpec(
        id="deepseek",
        label="DeepSeek Harness (preview)",
        command="dsh",
        config_env="DSH_HOME",
        default_home=".dsh",
        skill_sources=("native", "agents"),
        start_command=("dsh", "web"),
        play_entry="/play",
        prompt_surface="structured_elicitation",
    ),
)

HARNESS_BY_ID = {spec.id: spec for spec in HARNESS_SPECS}


def home_path(
    spec: HarnessSpec,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    owner = Path.home() if home is None else home
    values = os.environ if environ is None else environ
    return Path(values.get(spec.config_env, owner / spec.default_home)).expanduser()


def shared_agents_home(
    *, home: Path | None = None, environ: Mapping[str, str] | None = None
) -> Path:
    owner = Path.home() if home is None else home
    values = os.environ if environ is None else environ
    return Path(values.get("AGENTS_HOME", owner / ".agents")).expanduser()


def shared_agents_config_home(
    *, home: Path | None = None, environ: Mapping[str, str] | None = None
) -> Path:
    owner = Path.home() if home is None else home
    values = os.environ if environ is None else environ
    return Path(
        values.get("AGENTS_CONFIG_HOME", owner / ".config" / "agents")
    ).expanduser()


def skill_roots(
    spec: HarnessSpec,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, ...]:
    roots = {
        "native": home_path(spec, home=home, environ=environ) / "skills",
        "agents": shared_agents_home(home=home, environ=environ) / "skills",
        "agents-config": shared_agents_config_home(home=home, environ=environ)
        / "skills",
    }
    return tuple(roots[source] for source in spec.skill_sources)


def native_markers(
    spec: HarnessSpec,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, ...]:
    """Return app-owned markers; shared skill roots never prove app presence."""

    owner = Path.home() if home is None else home
    values = os.environ if environ is None else environ
    markers = [home_path(spec, home=owner, environ=environ)]
    if spec.id == "cursor" and spec.config_env not in values:
        markers.extend(
            (
                Path("/Applications/Cursor.app"),
                owner / "Applications" / "Cursor.app",
            )
        )
    return tuple(markers)


def detect_harness(
    spec: HarnessSpec,
    *,
    resolver: ExecutableResolver = shutil.which,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[bool, str | None]:
    command = resolver(spec.command)
    detected = command is not None or any(
        marker.exists() for marker in native_markers(spec, home=home, environ=environ)
    )
    return detected, command


def supported_harnesses() -> tuple[str, ...]:
    return tuple(spec.id for spec in HARNESS_SPECS)


def labels() -> dict[str, str]:
    return {spec.id: spec.label for spec in HARNESS_SPECS}


def native_prompt_surfaces() -> dict[str, str]:
    return {
        spec.id: spec.prompt_surface
        for spec in HARNESS_SPECS
        if spec.prompt_surface != "structured_elicitation"
    }
