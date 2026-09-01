"""Canonical harness capabilities for installation and runtime handoffs."""

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
    rote_target: str
    config_env: str
    default_home: str
    skill_sources: tuple[str, ...]
    start_command: tuple[str, ...]
    play_entry: str
    setup_entry: str
    delivery: str
    hook_style: str
    prompt_surface: str
    glyph: str


@dataclass(frozen=True)
class HostedHarnessSpec:
    """Describe an agent whose runtime lives outside the local machine."""

    id: str
    label: str
    app_bundle: str
    app_env: str
    compatibility_harness: str
    execution_host: str
    delivery: str
    play_entry: str
    setup_entry: str
    glyph: str


HARNESS_SPECS = (
    HarnessSpec(
        id="codex",
        label="Codex",
        command="codex",
        rote_target="codex",
        config_env="CODEX_HOME",
        default_home=".codex",
        skill_sources=("native",),
        start_command=("codex",),
        play_entry="$play",
        setup_entry="$rote-setup",
        delivery="marketplace",
        hook_style="nested-json",
        prompt_surface="request_user_input",
        glyph="◆",
    ),
    HarnessSpec(
        id="claude",
        label="Claude Code",
        command="claude",
        rote_target="claude-code",
        config_env="CLAUDE_CONFIG_DIR",
        default_home=".claude",
        skill_sources=("native",),
        start_command=("claude",),
        play_entry="/play",
        setup_entry="/rote-setup",
        delivery="marketplace",
        hook_style="nested-json",
        prompt_surface="askquestion",
        glyph="✦",
    ),
    HarnessSpec(
        id="kimi",
        label="Kimi",
        command="kimi",
        rote_target="kimi-code-cli",
        config_env="KIMI_CONFIG_DIR",
        default_home=".kimi",
        skill_sources=("native", "agents-config", "agents"),
        start_command=("kimi",),
        play_entry="/skill:play",
        setup_entry="/skill:rote-setup",
        delivery="skill-directory",
        hook_style="none",
        prompt_surface="askquestion",
        glyph="●",
    ),
    HarnessSpec(
        id="cursor",
        label="Cursor",
        command="cursor",
        rote_target="cursor",
        config_env="CURSOR_CONFIG_DIR",
        default_home=".cursor",
        skill_sources=("native", "agents"),
        start_command=("cursor",),
        play_entry="/play",
        setup_entry="/rote-setup",
        delivery="cursor-plugin",
        hook_style="flat-json",
        prompt_surface="structured_elicitation",
        glyph="⌁",
    ),
    HarnessSpec(
        id="hermes",
        label="Hermes Agent",
        command="hermes",
        rote_target="hermes-agent",
        config_env="HERMES_HOME",
        default_home=".hermes",
        skill_sources=("native",),
        start_command=("hermes",),
        play_entry="/play",
        setup_entry="/rote-setup",
        delivery="skill-directory",
        hook_style="none",
        prompt_surface="structured_elicitation",
        glyph="◈",
    ),
    HarnessSpec(
        id="opencode",
        label="OpenCode",
        command="opencode",
        rote_target="opencode",
        config_env="OPENCODE_CONFIG_DIR",
        default_home=".config/opencode",
        skill_sources=("native", "agents"),
        start_command=("opencode",),
        play_entry="/play",
        setup_entry="use the rote-setup skill",
        delivery="command-bridge",
        hook_style="none",
        prompt_surface="structured_elicitation",
        glyph="◇",
    ),
    HarnessSpec(
        id="deepseek",
        label="DeepSeek Harness (preview)",
        command="dsh",
        rote_target="agents-md",
        config_env="DSH_HOME",
        default_home=".dsh",
        skill_sources=("native", "agents"),
        start_command=("dsh", "web"),
        play_entry="/play",
        setup_entry="/rote-setup",
        delivery="skill-directory",
        hook_style="none",
        prompt_surface="structured_elicitation",
        glyph="◌",
    ),
)

HARNESS_BY_ID = {spec.id: spec for spec in HARNESS_SPECS}

HOSTED_HARNESS_SPECS = (
    HostedHarnessSpec(
        id="grok",
        label="Grok Bot",
        app_bundle="Grok Bot.app",
        app_env="GROK_BOT_APP",
        compatibility_harness="cursor",
        execution_host="registered-computer",
        delivery="agent-library-import",
        play_entry="/play",
        setup_entry="import the Play skill",
        glyph="✧",
    ),
)

HOSTED_HARNESS_BY_ID = {spec.id: spec for spec in HOSTED_HARNESS_SPECS}


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


def hosted_markers(
    spec: HostedHarnessSpec,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, ...]:
    """Return local desktop markers for a hosted agent companion."""

    owner = Path.home() if home is None else home
    values = os.environ if environ is None else environ
    if spec.app_env in values:
        return (Path(values[spec.app_env]).expanduser(),)
    return (
        Path("/Applications") / spec.app_bundle,
        owner / "Applications" / spec.app_bundle,
    )


def detect_hosted_harness(
    spec: HostedHarnessSpec,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Detect only the local companion app, never its managed cloud VM."""

    return any(
        marker.exists()
        for marker in hosted_markers(spec, home=home, environ=environ)
    )


def supported_harnesses() -> tuple[str, ...]:
    return tuple(spec.id for spec in HARNESS_SPECS)


def labels() -> dict[str, str]:
    return {spec.id: spec.label for spec in HARNESS_SPECS}


def commands() -> dict[str, str]:
    return {spec.id: spec.command for spec in HARNESS_SPECS}


def target_ids() -> dict[str, str]:
    return {spec.id: spec.rote_target for spec in HARNESS_SPECS}


def launch_surfaces() -> dict[str, tuple[str, str]]:
    return {
        spec.id: (" ".join(spec.start_command), spec.play_entry)
        for spec in HARNESS_SPECS
    }


def native_prompt_surfaces() -> dict[str, str]:
    return {
        spec.id: spec.prompt_surface
        for spec in HARNESS_SPECS
        if spec.prompt_surface != "structured_elicitation"
    }
