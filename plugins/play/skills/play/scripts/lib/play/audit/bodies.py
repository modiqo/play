"""AST extraction over the Play's code bodies with ast-grep.

ast-grep matches one file at a time. This module runs the patterns and hands
back plain facts about each file; the correlation with deps.toml and the
frontmatter happens in :mod:`correlate`. If the binding is not importable the
rules are reported as skipped, never as passed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import Collected, Location
from .package import Package
from .rules import UNKNOWN_RULES_SKIPPED, rule

try:
    import ast_grep_py as _sg
except ImportError:  # pragma: no cover - exercised on hosts without the wheel
    _sg = None

# Constructs that parse on an older interpreter and raise at import time, or
# fail to parse at all. Each entry: rule kwargs, minimum version, alternative.
_PY_FEATURES: tuple[tuple[dict[str, Any], str, str, str], ...] = (
    (
        # Only inside a `type` node: parameter, return, and variable annotations.
        # A `|` in an ordinary expression (flags, set union, dict merge) is not one.
        {"pattern": "$A | $B", "inside": {"kind": "type", "stopBy": "end"}},
        "3.10", "a PEP 604 union in an evaluated annotation",
        "add `from __future__ import annotations` or use typing.Optional",
    ),
    ({"kind": "match_statement"}, "3.10", "a `match` statement", "rewrite as if/elif"),
    (
        {"kind": "import_statement", "has": {"regex": "^tomllib$", "stopBy": "end"},
         "not": {"inside": {"kind": "try_statement", "stopBy": "end"}}},
        "3.11", "an unguarded `import tomllib`", "guard it with try/except ImportError and fall back to tomli",
    ),
    ({"kind": "except_clause", "regex": r"^except\s*\*"}, "3.11", "`except*`", "handle ExceptionGroup explicitly"),
    ({"kind": "type_alias_statement"}, "3.12", "a `type` alias statement", "use typing.TypeAlias"),
)
_FUTURE_ANNOTATIONS = "from __future__ import annotations"

_TS_SPAWNS: tuple[tuple[str, str, str], ...] = (
    # (pattern, meta-variable holding the command, rule id)
    ("new Deno.Command($C, $$$R)", "C", "DENO_COMMAND_UNDECLARED"),
    ("Deno.run({ cmd: [$C, $$$R] })", "C", "DENO_COMMAND_UNDECLARED"),
    ("spawn($C, $$$R)", "C", "CHILD_PROCESS_UNDECLARED"),
    ("execFile($C, $$$R)", "C", "CHILD_PROCESS_UNDECLARED"),
    ("exec($C, $$$R)", "C", "CHILD_PROCESS_UNDECLARED"),
    ("spawnSync($C, $$$R)", "C", "CHILD_PROCESS_UNDECLARED"),
    ("execSync($C, $$$R)", "C", "CHILD_PROCESS_UNDECLARED"),
    ("rote.exec({ argv: [$C, $$$R] $$$O })", "C", "ROTE_EXEC_UNDECLARED"),
    ("rote.exec({ argv: [$C] $$$O })", "C", "ROTE_EXEC_UNDECLARED"),
)
# Every subprocess entry point, with the argument node captured whole; whether
# it is a literal list, a literal string, or a variable is decided per match.
_PY_SPAWN_CALLS = ("run", "check_output", "check_call", "call", "Popen")
_PY_SPAWNS: tuple[str, ...] = tuple(
    pattern
    for fn in _PY_SPAWN_CALLS
    for pattern in (f"subprocess.{fn}($ARGS, $$$K)", f"subprocess.{fn}($ARGS)")
)
_SHELL_BUILTINS = {
    "echo", "exit", "cd", "set", "export", "test", "[", "printf", "read", "shift", "return", "true", "false",
    "local", "eval", "exec", "trap", "wait", "source", ".", "unset", "if", "then", "else", "fi", "for", "do",
    "done", "while", "case", "esac", "break", "continue", "command", "type", "alias", "declare", "readonly",
}
_STRING = re.compile(r"""^\s*(['"`])(.*)\1\s*$""", re.S)
_PARAM_READ = re.compile(r"param(?:eter)?s\??\.([A-Za-z_][A-Za-z0-9_]*)|param(?:eter)?s\[[\"']([^\"']+)[\"']\]")
_DYNAMIC_PARAM_ACCESS = re.compile(
    r"Deno\.args|process\.argv|parseArgs\(|ROTE_PARAM|Object\.(?:entries|keys|values)\(\s*(?:ctx\.)?(?:run\.)?param(?:eter)?s"
    r"|\{[^}]*\}\s*=\s*(?:ctx\.)?(?:run\.)?param(?:eter)?s\b|\bparam(?:eter)?s\s*\)|\bparam(?:eter)?s\s*,"
)


@dataclass
class Spawn:
    file: str
    line: int
    rule_id: str
    command: str | None  # None when the value is not a literal


@dataclass
class BodyAnalysis:
    available: bool = True
    stranded_guard: bool = False
    reads_stdout_text: list[tuple[str, int]] = field(default_factory=list)
    checks_truncated: bool = False
    params_read: set[str] = field(default_factory=set)
    params_read_dynamically: bool = False
    params_named_as_strings: set[str] = field(default_factory=set)
    spawns: list[Spawn] = field(default_factory=list)
    shell_commands: set[str] = field(default_factory=set)      # AST-confirmed: shown as reach
    shell_mentions: set[str] = field(default_factory=set)      # loose positional scan: only for "is it used"

    @property
    def reach_is_partial(self) -> bool:
        """True when some command the Play runs could not be resolved statically."""
        return any(spawn.command is None for spawn in self.spawns)
    python_needs: list[tuple[str, int, str, str, str]] = field(default_factory=list)  # file, line, needs, construct, alternative
    collected: Collected = field(default_factory=Collected)


def _root(source: str, language: str) -> Any:
    assert _sg is not None  # callers check ``available`` first
    return _sg.SgRoot(source, language).root()


def _py_command(args: Any) -> str | None:
    """The command a subprocess call runs, when it is written down: the first
    element of a literal list, or a literal string. Anything else is dynamic."""
    if args is None:
        return None
    if args.kind() == "binary_operator":  # ["git"] + rest: the command is still written down
        left = next((child for child in args.children() if child.is_named()), None)
        return _py_command(left) if left is not None and left.kind() in {"list", "string"} else None
    if args.kind() == "list":
        first = next((child for child in args.children() if child.is_named()), None)
        return _literal(first.text()) if first is not None else None
    if args.kind() == "string":
        text = _literal(args.text())
        return text.split()[0] if text else None
    return None


def _literal(text: str) -> str | None:
    match = _STRING.match(text)
    return match.group(2) if match else None


def _line(node: Any) -> int:
    return int(node.range().start.line) + 1


def _scan_typescript(analysis: BodyAnalysis, file: str, source: str, line_offset: int) -> None:
    root = _root(source, "typescript")
    if root.find(pattern="if (import.meta.main) { $$$B }") is not None:
        analysis.stranded_guard = True
    for node in root.find_all(any=[{"pattern": "$X.stdout.text"}, {"pattern": "$X.stdout?.text"}]):
        analysis.reads_stdout_text.append((file, _line(node) + line_offset))
    if root.find(any=[{"pattern": "$X.stdout.truncated"}, {"pattern": "$X.stdout?.truncated"}]) is not None:
        analysis.checks_truncated = True
    for pattern, var, rule_id in _TS_SPAWNS:
        for node in root.find_all(pattern=pattern):
            target = node.get_match(var)
            literal = _literal(target.text()) if target is not None else None
            # exec('git remote get-url origin') runs a shell line; the tool is its first word.
            command = literal.split()[0] if literal and literal.strip() else None
            analysis.spawns.append(Spawn(file, _line(node) + line_offset, rule_id, command))
    for match in _PARAM_READ.finditer(source):
        analysis.params_read.add(match.group(1) or match.group(2))
    for match in re.finditer(r"""["']([A-Za-z_][A-Za-z0-9_-]*)["']""", source):
        analysis.params_named_as_strings.add(match.group(1))
    if _DYNAMIC_PARAM_ACCESS.search(source):
        analysis.params_read_dynamically = True


def _find_all(analysis: BodyAnalysis, root: Any, label: str, **rule_kwargs: Any) -> list[Any]:
    """Run one rule; a rule the bundled grammar cannot express is skipped by name, not fatal."""
    try:
        return list(root.find_all(**rule_kwargs))
    except Exception as error:  # noqa: BLE001
        reason = str(error).splitlines()[-1].strip() if str(error) else type(error).__name__
        analysis.collected.unknown(UNKNOWN_RULES_SKIPPED, label, f"rule could not run on this ast-grep build: {reason}")
        return []


def _scan_python(analysis: BodyAnalysis, file: str, source: str) -> None:
    root = _root(source, "python")
    has_future = root.find(pattern=_FUTURE_ANNOTATIONS) is not None
    for rule_kwargs, needs, construct, alternative in _PY_FEATURES:
        if has_future and needs == "3.10" and "$A | $B" in str(rule_kwargs.get("pattern")):
            continue
        for node in _find_all(analysis, root, f"{file}: {construct}", **rule_kwargs):
            analysis.python_needs.append((file, _line(node), needs, construct, alternative))
    seen: set[int] = set()
    for pattern in _PY_SPAWNS:
        for node in _find_all(analysis, root, f"{file}: subprocess", pattern=pattern):
            line = _line(node)
            if line in seen:
                continue
            seen.add(line)
            analysis.spawns.append(Spawn(file, line, "SUBPROCESS_UNDECLARED", _py_command(node.get_match("ARGS"))))


_SHELL_COMMAND_POSITION = re.compile(
    r"(?:^|[|;&(]|\$\(|\bthen\b|\bdo\b|\belse\b|-exec\s|-execdir\s|\bxargs\s(?:-[\w]+\s+)*)"
    r"\s*(?:sudo\s+|env\s+|command\s+|exec\s+|time\s+|nice\s+)?([A-Za-z_][\w.+-]*)", re.M)


def _command_name(raw: str) -> str | None:
    name = raw.strip().strip("\"'")
    if not name or name.startswith("$") or name.startswith("-") or "=" in name:
        return None
    name = name.rsplit("/", 1)[-1]  # /bin/ps and ps are the same tool
    return None if name in _SHELL_BUILTINS else name


def _scan_shell(analysis: BodyAnalysis, file: str, source: str) -> None:
    """Commands a shell resource invokes, so deps.toml can be checked against them.

    tree-sitter-bash drops commands after some quoting it cannot model, so the
    AST names are complemented by a conservative scan of command positions.
    """
    root = _root(source, "bash")
    for node in _find_all(analysis, root, f"{file}: commands", kind="command_name"):
        name = _command_name(node.text())
        if name:
            analysis.shell_commands.add(name)
    stripped = "\n".join(line.split("#", 1)[0] for line in source.splitlines())
    for match in _SHELL_COMMAND_POSITION.finditer(stripped):
        name = _command_name(match.group(1))
        if name:
            analysis.shell_mentions.add(name)


_TEST_FILE = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$|conftest\.py$)")


def is_test_file(relative: str) -> bool:
    """Shipped tests never run for a consumer; their spawns and constructs are not the Play's reach."""
    return _TEST_FILE.search(relative) is not None


def analyze(package: Package) -> BodyAnalysis:
    analysis = BodyAnalysis()
    if _sg is None:
        analysis.available = False
        analysis.collected.unknown(
            UNKNOWN_RULES_SKIPPED, "bodies",
            "ast-grep-py is not installed; body rules (stranded body, spawned commands, "
            "Python floor, truncation handling) did not run",
        )
        return analysis
    front = package.frontmatter
    if front.body:
        _scan_typescript(analysis, "main.ts", front.body, front.body_line_offset)
    for path in package.python_resources:
        relative = package.relative(path)
        if not is_test_file(relative):
            _scan_python(analysis, relative, _read(path))
    for path in package.shell_resources:
        relative = package.relative(path)
        if not is_test_file(relative):
            _scan_shell(analysis, relative, _read(path))
    for path in package.script_resources:
        relative = package.relative(path)
        if not is_test_file(relative):
            _scan_typescript(analysis, relative, _read(path), 0)
    # Inline code carried in step argv is part of the Play's reach too.
    for name, step in front.steps.items():
        argv = step.get("argv")
        if not isinstance(argv, list) or len(argv) < 3 or str(argv[1]) not in {"-c", "-e"}:
            continue
        interpreter, code = str(argv[0]), str(argv[2])
        if interpreter in {"sh", "bash", "zsh"}:
            _scan_shell(analysis, f"steps.{name} (inline shell)", code)
        elif interpreter in {"python3", "python"}:
            _scan_python(analysis, f"steps.{name} (inline python)", code)
    return analysis


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def correlate(package: Package, analysis: BodyAnalysis) -> Collected:
    """Turn body facts into findings using the package's declarations."""
    out = Collected()
    out.extend(analysis.collected)
    if not analysis.available:
        return out
    front = package.frontmatter
    if front.steps and analysis.stranded_guard and front.execution_model != "steps_with_presentation":
        out.add(rule("BODY_STRANDED").finding(Location(file="main.ts")))
    if analysis.reads_stdout_text and not analysis.checks_truncated:
        file, line = analysis.reads_stdout_text[0]
        out.add(rule("PRESENTATION_READS_PREVIEW_IGNORES_TRUNCATED").finding(Location(file=file, line=line), file=file))
    dynamic_seen: set[str] = set()
    for spawn in analysis.spawns:
        loc = Location(file=spawn.file, line=spawn.line)
        if spawn.command is None:
            if spawn.file not in dynamic_seen:  # one judgment per file, not per call site
                dynamic_seen.add(spawn.file)
                out.add(rule("DYNAMIC_COMMAND_UNRESOLVABLE").finding(loc, file=spawn.file, line=spawn.line))
        elif package.deps_present and spawn.command not in package.tools:
            out.add(rule(spawn.rule_id).finding(loc, file=spawn.file, line=spawn.line, command=spawn.command))
    if analysis.python_needs:
        declared = _declared_python_floor(package)
        for file, line, needs, construct, alternative in analysis.python_needs:
            if declared is None or _version_tuple(declared) < _version_tuple(needs):
                out.add(rule("PY_FLOOR_TOO_LOW").finding(
                    Location(file=file, line=line), file=file, line=line, construct=construct,
                    needs=needs, declared=declared or "none", alternative=alternative))
    return out


def _declared_python_floor(package: Package) -> str | None:
    for name in ("python3", "python"):
        tool = package.tools.get(name)
        if tool and tool.version_requirement:
            match = re.search(r"(\d+(?:\.\d+){0,2})", tool.version_requirement)
            if match:
                return match.group(1)
    return None


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])
