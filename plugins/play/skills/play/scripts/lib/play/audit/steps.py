"""Per-step measurement from the frontmatter: shape, reach, and the facts and
judgments a step's argv alone can support."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .model import Collected, Location, StepShape
from .package import Package
from .rules import UNKNOWN_INLINE_BODY, rule

INLINE_LIMIT = 256
INTERPRETERS = {"python3", "python", "node", "deno", "ruby", "perl"}
INTERPRETER_FLOORS = {"python3": "3.10.0", "python": "3.10.0", "node": "20.0.0", "deno": "1.40.0"}
UNRELIABLE_EXIT = {"find", "grep", "diff", "rsync"}
MACOS_ONLY = {
    "pbcopy", "pbpaste", "open", "sw_vers", "mdfind", "osascript", "defaults", "security",
    "plutil", "ditto", "xcrun", "launchctl", "diskutil", "system_profiler", "networksetup", "say", "afplay",
}
LINUX_ONLY = {"apt", "apt-get", "systemctl", "journalctl", "xdg-open", "dpkg", "yum", "dnf", "pacman", "lsb_release", "nproc"}
COREUTILS_ABSENT_ON_MACOS = {"timeout", "realpath", "sha256sum", "md5sum", "shuf", "tac", "seq -w"}
BSD_GNU_FLAGS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsed\s+-i(?=\s+(?!'')\S)"), "sed -i with a suffix argument"),
    (re.compile(r"\bsed\s+-i\s+''"), "sed -i '' (BSD form)"),
    (re.compile(r"\bstat\s+-[fc]\b"), "stat -f / stat -c"),
    (re.compile(r"\bdate\s+-[vd]\b"), "date -v / date -d"),
    (re.compile(r"\bxargs\s+-r\b"), "xargs -r"),
    (re.compile(r"\breadlink\s+-f\b"), "readlink -f"),
    (re.compile(r"\bgrep\s+-P\b"), "grep -P"),
)
BASHISMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\[\["), "[[ ]]"),
    (re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\["), "array expansion"),
    (re.compile(r"\bdeclare\s+-"), "declare"),
    (re.compile(r"\blocal\s+[A-Za-z_]"), "local"),
    (re.compile(r"<<<"), "here-string"),
    (re.compile(r"\$'"), "$'...' quoting"),
    (re.compile(r"\bfunction\s+[A-Za-z_]+\s*\{"), "function keyword"),
)
_RESOURCE_TOKEN = re.compile(r"@resource\{([^}]+)\}")
_RESOURCE_PATH = re.compile(r"(?<![\w/])resources/([\w./-]+)")
_PARAM = re.compile(r"\$([A-Za-z_][A-Za-z0-9_-]*)")
_HOME_PATH = re.compile(r"(/Users/[^/\s'\"]+|/home/[^/\s'\"]+)")


@dataclass
class StepAnalysis:
    shapes: list[StepShape] = field(default_factory=list)
    commands_run: set[str] = field(default_factory=set)
    params_read: set[str] = field(default_factory=set)
    collected: Collected = field(default_factory=Collected)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def _inline_code(argv: list[str]) -> tuple[str | None, str]:
    """Return (interpreter, code) when argv is ``<interp> -c/-e <code>``."""
    if len(argv) >= 3 and argv[1] in {"-c", "-e"}:
        return argv[0], argv[2]
    return None, ""


def _kind_label(step: dict[str, Any], command: str | None) -> tuple[str, str]:
    kind = str(step.get("type") or "")
    if kind == "process.exec":
        return "process", "runs a local command"
    if kind.startswith("browser"):
        return "browser", "drives a browser"
    if "endpoint" in step or kind.startswith("adapter"):
        return "adapter", "calls a service"
    return kind or "unknown", kind or "step"


def analyze(package: Package) -> StepAnalysis:
    result = StepAnalysis()
    out = result.collected
    front = package.frontmatter
    steps = front.steps
    names = set(steps)
    fixtures = front.presentation_fixtures

    for name, step in steps.items():
        loc = Location(path=f"steps.{name}")
        argv_raw = step.get("argv")
        argv = [str(item) for item in argv_raw] if isinstance(argv_raw, list) else []
        command = argv[0] if argv else None
        kind, label = _kind_label(step, command)
        shape = StepShape(name=name, kind=kind, label=label)
        depends = step.get("depends_on")
        shape.depends_on = [str(d) for d in depends] if isinstance(depends, list) else []
        for target in shape.depends_on:
            if target not in names:
                out.add(rule("DEPENDS_ON_UNKNOWN").finding(loc, step=name, target=target))
        joined = " ".join(_strings(step))
        for param in _PARAM.findall(joined):
            if param != "item":
                result.params_read.add(param)
                shape.reads_params.append(param)
        shape.reads_params = sorted(set(shape.reads_params))
        if kind == "adapter":
            shape.endpoint = str(step.get("endpoint") or "")
            shape.operation = str(step.get("method") or step.get("operation") or "") or None
        for_each = step.get("for_each")
        if isinstance(for_each, str) and for_each:
            shape.fan_out = True
            if "stdout.text" in for_each:
                out.add(rule("FANOUT_OVER_PREVIEW").finding(loc, step=name, source=for_each))
        for token in _RESOURCE_TOKEN.findall(joined) + _RESOURCE_PATH.findall(joined):
            shape.resources.append(token)
            if not package.has_resource(token):
                out.add(rule("RESOURCE_MISSING").finding(loc, step=name, resource=token))
        shape.resources = sorted(set(shape.resources))

        if kind == "process" and command:
            result.commands_run.add(command)
            shape.commands.append(command)
            if "timeout_ms" not in step:
                out.add(rule("STEP_NO_TIMEOUT").finding(loc, step=name))
            if package.deps_present and command not in package.tools and not command.startswith("@"):
                out.add(rule("TOOL_UNDECLARED").finding(loc, step=name, command=command))
            tool = package.tools.get(command)
            if command in INTERPRETERS and tool is not None and not tool.version_requirement:
                out.add(rule("INTERPRETER_FLOOR_MISSING").finding(
                    loc, step=name, command=command, floor=INTERPRETER_FLOORS.get(command, "latest")))
            if command in UNRELIABLE_EXIT:
                out.add(rule("UNRELIABLE_EXIT_STATUS").finding(loc, step=name, command=command))
            if command in MACOS_ONLY:
                out.add(rule("MACOS_ONLY_COMMAND").finding(loc, step=name, command=command))
            if command in LINUX_ONLY:
                out.add(rule("LINUX_ONLY_COMMAND").finding(loc, step=name, command=command))
            if command in COREUTILS_ABSENT_ON_MACOS:
                out.add(rule("COREUTILS_ABSENT_ON_MACOS").finding(loc, step=name, command=command))
            argv_text = " ".join(argv)
            for pattern, construct in BSD_GNU_FLAGS:
                if pattern.search(argv_text):
                    out.add(rule("BSD_GNU_FLAG").finding(loc, step=name, construct=construct))
            home = _HOME_PATH.search(argv_text)
            if home:
                out.add(rule("ABSOLUTE_HOME_PATH").finding(loc, step=name, path=home.group(1)))

            interpreter, code = _inline_code(argv)
            if interpreter is not None:
                if len(code) > INLINE_LIMIT:
                    out.add(rule("INLINE_CODE_PAYLOAD").finding(loc, step=name, length=len(code)))
                if interpreter in {"node", "deno"}:
                    shape.unread_body = True
                    out.unknown(UNKNOWN_INLINE_BODY, f"steps.{name}",
                                f"inline `{interpreter} -e` body is not read by this inspection")
                if interpreter in {"sh", "bash", "zsh"}:
                    for pattern, construct in BASHISMS:
                        if interpreter == "sh" and pattern.search(code):
                            out.add(rule("BASHISM_IN_SH").finding(loc, step=name, construct=construct))
                            break
                    if "pipefail" in code:
                        for tool_name in UNRELIABLE_EXIT:
                            if re.search(rf"\b{tool_name}\b[^|\n]*\|", code) and "|| true" not in code:
                                out.add(rule("PIPEFAIL_PROPAGATES").finding(loc, step=name, command=tool_name))
                                break
                    for tool_name in sorted(UNRELIABLE_EXIT):
                        if re.search(rf"(^|[;&|(\s]){tool_name}\s", code) and "|| true" not in code:
                            shape.commands.append(tool_name)
                            result.commands_run.add(tool_name)
        result.shapes.append(shape)

    if fixtures:
        for fixture_name, spec in fixtures.items():
            for value in _strings(spec):
                if "/" in value and not (package.root / value).is_file() and not package.has_resource(value):
                    out.add(rule("FIXTURE_MISSING").finding(
                        Location(path=f"presentation_fixtures.{fixture_name}"), fixture=value))
    return result
