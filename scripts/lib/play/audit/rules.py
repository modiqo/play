"""The rule registry: what each finding means, who fixes it, and how.

A rule's class is decided here, once. A fact is provable from the package
alone; a judgment needs context the package does not carry and ships to
authors only. Message and fix templates are formatted with the evidence the
extractor supplies, so the wording lives in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model import Finding, FindingClass, Location, Scope

OWNER_AUTHORING = "rote-flow-authoring"
OWNER_TROUBLESHOOTING = "rote-troubleshooting"
OWNER_SHELL = "rote-shell"
OWNER_TYPESCRIPT = "rote-typescript-transformations"
OWNER_REGISTRY = "rote-registry"

ISSUE = "https://github.com/modiqo/rote/issues/"


@dataclass(frozen=True)
class Rule:
    id: str
    cls: FindingClass
    owner: str
    message: str
    fix: str
    scope: Scope = "package"
    related_issue: str | None = None
    precision: float | None = None

    def finding(self, location: Location, **evidence: Any) -> Finding:
        return Finding(
            id=self.id,
            cls=self.cls,
            scope=self.scope,
            owner=self.owner,
            message=self.message.format(**evidence),
            location=location,
            fix=self.fix.format(**evidence),
            evidence=evidence,
            related_issue=self.related_issue,
            precision=self.precision,
        )


_RULES: tuple[Rule, ...] = (
    # ── facts ────────────────────────────────────────────────────────────
    Rule(
        "PARAMETERS_UNDER_METADATA", "fact", OWNER_AUTHORING,
        "`parameters:` is nested under `metadata:`; rote accepts it by fallback but readers see it as dropped.",
        "Dedent `parameters:` so it is a sibling of `metadata:` and `steps:`.",
        related_issue=ISSUE + "2178",
    ),
    Rule(
        "BODY_STRANDED", "fact", OWNER_AUTHORING,
        "steps are declared and the body guards `run()` behind `import.meta.main`, but `execution_model` is not `steps_with_presentation`; the body never runs.",
        "Move the work into steps (a resource script, not inline code), set `metadata.execution_model: steps_with_presentation`, and let the body render what the steps found.",
        related_issue=ISSUE + "2178",
    ),
    Rule(
        "DEPS_TOML_MISSING", "fact", OWNER_AUTHORING,
        "process steps run {commands} but the package ships no deps.toml, so consumers get no dependency gate.",
        "Add deps.toml declaring every command a step runs, with install hints and a version floor for interpreters.",
    ),
    Rule(
        "TOOL_UNDECLARED", "fact", OWNER_AUTHORING,
        "`{command}` is run by step(s) {step} but deps.toml does not declare it.",
        "Add a `[[tools]]` entry for `{command}` to deps.toml.",
    ),
    Rule(
        "RESOURCE_MISSING", "fact", OWNER_AUTHORING,
        "step `{step}` references `{resource}`, which is not shipped in resources/.",
        "Add `resources/{resource}` to the package or fix the reference.",
    ),
    Rule(
        "FIXTURE_MISSING", "fact", OWNER_AUTHORING,
        "declared presentation fixture `{fixture}` is not shipped.",
        "Add the fixture file or remove it from `presentation_fixtures`.",
    ),
    Rule(
        "MANIFEST_DRIFT", "fact", OWNER_AUTHORING,
        "the generated manifest disagrees with the frontmatter on {field}: {detail}.",
        "Re-release the Play so the manifest is regenerated from the current frontmatter.",
    ),
    Rule(
        "DEPENDS_ON_UNKNOWN", "fact", OWNER_AUTHORING,
        "step `{step}` depends on `{target}`, which is not a declared step.",
        "Point `depends_on` at a declared step name.",
    ),
    Rule(
        "STEP_NO_TIMEOUT", "fact", OWNER_AUTHORING,
        "{count} step(s) have no `timeout_ms` and inherit rote's 30 s default: {step}.",
        "Add `timeout_ms` to each step, sized to its expected duration; a scan over a large tree needs more than 30 s.",
    ),
    Rule(
        "INTERPRETER_FLOOR_MISSING", "fact", OWNER_AUTHORING,
        "`{command}` is run by step(s) {step}; deps.toml declares it without a `version_requirement`, and a stock macOS ships python3 3.9.6.",
        "Add `version_requirement = \">={floor}\"` to the `{command}` entry in deps.toml.",
        related_issue=ISSUE + "2179",
    ),
    Rule(
        "PY_FLOOR_TOO_LOW", "fact", OWNER_AUTHORING,
        "{file}:{line} uses {construct}, which needs Python {needs}; the declared floor is {declared}.",
        "Either raise `version_requirement` to `>={needs}` in deps.toml or rewrite the construct ({alternative}).",
        related_issue=ISSUE + "2179",
    ),
    Rule(
        "INLINE_CODE_PAYLOAD", "fact", OWNER_AUTHORING,
        "step `{step}` carries {length} characters of inline code in argv; the limit is 256.",
        "Move the code to `resources/` and invoke it with `@resource{{...}}`.",
        related_issue=ISSUE + "2178",
    ),
    Rule(
        "FANOUT_OVER_PREVIEW", "fact", OWNER_TROUBLESHOOTING,
        "step `{step}` fans out over `{source}`, which is the 64 KiB preview of the upstream stdout; larger lists fail to parse at column 65536.",
        "Bound the upstream output, or declare `capture.stdout.file` and read the full artifact.",
        related_issue=ISSUE + "2180",
    ),
    Rule(
        "DENO_COMMAND_UNDECLARED", "fact", OWNER_TYPESCRIPT,
        "{file}:{line} spawns `{command}` with Deno.Command, which deps.toml does not declare.",
        "Declare `{command}` in deps.toml or move the call into a process step.",
    ),
    Rule(
        "CHILD_PROCESS_UNDECLARED", "fact", OWNER_TYPESCRIPT,
        "{file}:{line} spawns `{command}` with child_process, which deps.toml does not declare.",
        "Declare `{command}` in deps.toml or move the call into a process step.",
    ),
    Rule(
        "SUBPROCESS_UNDECLARED", "fact", OWNER_SHELL,
        "{file}:{line} spawns `{command}` with subprocess, which deps.toml does not declare.",
        "Declare `{command}` in deps.toml.",
    ),
    Rule(
        "ROTE_EXEC_UNDECLARED", "fact", OWNER_SHELL,
        "{file}:{line} runs `{command}` through rote.exec, which deps.toml does not declare.",
        "Declare `{command}` in deps.toml and in the call's `deps` list.",
    ),
    Rule(
        "ABSOLUTE_HOME_PATH", "fact", OWNER_AUTHORING,
        "step `{step}` embeds the absolute home path `{path}`; it only resolves on the author's machine.",
        "Replace the path with a parameter or a path relative to the workspace.",
    ),
    Rule(
        "ADAPTER_OPERATION_UNKNOWN", "fact", OWNER_REGISTRY,
        "step `{step}` calls `{operation}` on `{adapter}`, which exposes only: {known}.",
        "Use an operation the adapter exposes, or update the adapter.",
    ),
    Rule(
        "ADAPTER_SOURCE_PROVENANCE_DIFFERS", "fact", OWNER_REGISTRY,
        "the Play pins `{pinned}` for `{adapter}` but the installed copy comes from `{installed}` with the same fingerprint; rote refuses this on the consumer's machine.",
        "Pin the canonical adapter for this fingerprint, or wait for rote to resolve by fingerprint (modiqo/rote#2181).",
        scope="host",
        related_issue=ISSUE + "2181",
    ),
    Rule(
        "PRESENTATION_FIXTURE_MISSING", "fact", OWNER_AUTHORING,
        "the presentation reads step(s) {step} but no `presentation_fixtures` entry covers them; `rote play lint` cannot exercise the rendering.",
        "Run `play audit fixtures <path>` after a verified run to record each step's observation and declare it.",
    ),
    # ── judgments ────────────────────────────────────────────────────────
    Rule(
        "NEGATIVE_CASES_MISSING", "judgment", OWNER_TROUBLESHOOTING,
        "no negative cases are packed under resources/cases; nothing proves the presentation reports a failed, blocked, or truncated step honestly.",
        "Run `play audit fixtures <path>` to pack partial, truncated, and blocked cases per step, then `play audit rehearse`.",
    ),
    Rule(
        "PARAM_UNREFERENCED", "judgment", OWNER_AUTHORING,
        "parameter `{param}` is declared but no step argv, for_each, or presentation body reads it.",
        "Wire `{param}` into a step or the presentation, or remove it from `parameters`.",
        related_issue=ISSUE + "2178",
        precision=1.0,  # 6/6 labelled true on the 2026-09-03 registry corpus
    ),
    Rule(
        "TOOL_DECLARED_UNUSED", "judgment", OWNER_AUTHORING,
        "deps.toml declares `{command}` but no step runs it.",
        "Remove the stale `[[tools]]` entry or add the step that needs it.",
        precision=1.0,  # 3/3 labelled true on the 2026-09-03 registry corpus
    ),
    Rule(
        "UNRELIABLE_EXIT_STATUS", "judgment", OWNER_TROUBLESHOOTING,
        "step `{step}` runs bare `{command}`; it exits 1 on a partial traversal (a protected folder on macOS) and the step fails with its output discarded.",
        "Wrap it: `sh -c '{command} ... || true'`, count unreadable paths from stderr, and report them as skipped.",
        related_issue=ISSUE + "2177",
    ),
    Rule(
        "PIPEFAIL_PROPAGATES", "judgment", OWNER_SHELL,
        "step `{step}` sets `pipefail` and pipes `{command}`; its partial-traversal exit status now fails the whole pipeline.",
        "Append `|| true` to the `{command}` stage or drop `pipefail` for that pipeline.",
        related_issue=ISSUE + "2177",
    ),
    Rule(
        "BASHISM_IN_SH", "judgment", OWNER_SHELL,
        "step `{step}` uses bash syntax ({construct}) under `sh -c`; dash and BSD sh reject it.",
        "Run the body with `bash -c` and declare bash in deps.toml, or rewrite in POSIX sh.",
    ),
    Rule(
        "MACOS_ONLY_COMMAND", "judgment", OWNER_SHELL,
        "step `{step}` runs `{command}`, which exists only on macOS.",
        "Guard it with a platform check or provide a Linux equivalent.",
    ),
    Rule(
        "LINUX_ONLY_COMMAND", "judgment", OWNER_SHELL,
        "step `{step}` runs `{command}`, which exists only on Linux.",
        "Guard it with a platform check or provide a macOS equivalent.",
    ),
    Rule(
        "BSD_GNU_FLAG", "judgment", OWNER_SHELL,
        "step `{step}` uses `{construct}`, which differs between BSD (macOS) and GNU (Linux) userlands.",
        "Use the portable form or branch on the platform.",
    ),
    Rule(
        "COREUTILS_ABSENT_ON_MACOS", "judgment", OWNER_SHELL,
        "step `{step}` runs `{command}`, which a stock macOS does not ship.",
        "Declare it in deps.toml with a brew install hint, or use a portable alternative.",
    ),
    Rule(
        "DYNAMIC_COMMAND_UNRESOLVABLE", "judgment", OWNER_TYPESCRIPT,
        "{file}:{line} spawns a command built at run time; the audit cannot check it against deps.toml.",
        "Spawn a literal command, or declare every command the value can take.",
    ),
    Rule(
        "PRESENTATION_READS_PREVIEW_IGNORES_TRUNCATED", "judgment", OWNER_TYPESCRIPT,
        "{file} reads `stdout.text` but never checks `stdout.truncated`; output over 64 KiB is silently cut.",
        "Check `stdout.truncated` and state that the result is partial when it is set.",
        related_issue=ISSUE + "2180",
    ),
)

RULES: dict[str, Rule] = {rule.id: rule for rule in _RULES}

# Unknown kinds. These are never findings.
UNKNOWN_INLINE_BODY = "INLINE_BODY_UNREAD"
UNKNOWN_ADAPTER = "ADAPTER_NOT_READABLE"
UNKNOWN_EXTRACTOR = "EXTRACTOR_FAILED"
UNKNOWN_RULES_SKIPPED = "RULES_SKIPPED"


def rule(rule_id: str) -> Rule:
    return RULES[rule_id]
