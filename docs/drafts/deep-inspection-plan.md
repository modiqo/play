# Play deep inspection: plan

Status: v3, in progress on branch `feat/play-audit` since 2026-09-03.

Shipped on the branch (milestone 1 plus the adapter and profile parts of 3): the fan-out runner with the fail-safe wrapper, the envelope, every fact and judgment rule listed below except `ADAPTER_AUTH_MISMATCH`, the consumer card, the author view, the inbox report, persistence and history under `PLAY_HOME`, `play-audit` with `history` and `show`, host profiles for stock macOS and Ubuntu LTS, adapter correlation through `rote adapter info`, and the card inside `play-inspect --card`. Since then: `play-audit-corpus` and the corpus measurement; `play audit fixtures` (positive fixtures from the last run plus partial, truncated, and blocked cases per step, never reachable from a step); `play audit rehearse` (cards per host profile, rote lint for positives, negative cases rendered through the presentation with rote's deno and SDK); `play audit handoff` with `--close` deltas; `play audit send`; the card on by default in `play-inspect`; controller policy lines in `prepare_candidate`, `author_release`, and `smoke_publication`. Not yet: a typed `choose_audit_handoffs` prompt (the policy asks the specialist to offer the choice), `candidate.audit_ref` and `publication.audit_ref` context fields, run outcomes appended to history after `verify_play_output`, and a registry inbox for `send` (it writes the report locally until one exists).

## Rehearsal measurement, 2026-09-03

`play audit rehearse` over 51 Plays (45 pulled from the registry, 6 with recorded runs): 348 negative cases rendered through the real presentations with rote's deno and SDK, 0 harness errors. 182 passed, 52 were weak (output changed but did not name the degraded step), 114 failed (output identical to the positive run, or the presentation threw). 21 Plays could not be rehearsed for lack of a recorded run or declared fixtures, and say so. The dominant failure is the truncated case: almost no presentation checks `stdout.truncated`, which is modiqo/rote#2180 seen from the author's side. Every scaffolded fixture passed `rote play lint`'s runtime checks, including steps with declared capture files.

## Corpus measurement, 2026-09-03

`play-audit-corpus` pulled 212 public Plays, kept 205 packages, and audited each. Every fact was re-derived from the package on disk by independent code: 295 facts verified, 0 contradicted. The sweep found and fixed, before this measurement: a union rule that matched any `|` in an assignment (39 false positives), wrong body line numbers, an unreferenced-parameter judgment blind to dynamic reads, and an unused-tool judgment blind to inline shell, `find -exec`, JavaScript resources, runtime dependencies, and path-declared tools. Remaining judgment hits were hand-labelled: unreferenced parameter 6/6 true, unused tool 3/3 true; dynamic-command and truncation-handling judgments are true by construction. Portability judgments had no hits in the corpus and stay unmeasured.

## Why

Five community reports in one week (modiqo/rote #2177 to #2181) had one shape: rote held the evidence and the surface reported green. A scan of the 13 Plays installed on one machine found 49 static findings across 11 kinds, including three of modiqo's own Plays. Play sits at the two moments that matter, before an author releases and before a consumer approves a run, and today it checks nothing about the Play itself.

## Two audiences, one analysis, two surfaces

The same static analysis feeds two very different outputs. They must never be confused.

**Author hygiene.** Everything the analysis can say, with a fix for each item and a named skill that applies it. Its job is to raise the quality of a Play before it is announced. It is opinionated and complete.

**Consumer report card.** A calm one-screen summary of what a Play is and does, attached to the inspect disclosure before the run prompt. Its job is to let a consumer decide with confidence. It never shows a list of problems. It shows the Play's shape, what it needs from this machine, and at most one plain sentence per thing that would stop it from running here.

## Operating principles

These override anything else in this document.

**Advisory, never blocking.** The audit informs; it does not gate. A consumer still sees the run prompt. An author still reaches `rote play release`. rote's own preflight remains the only thing that stops a run, and rote's own lint remains the only thing that refuses a release. The audit's job is to make sure both people saw what they were about to do.

**Fail safe, never fail the process.** The entrypoint always returns a valid envelope and always exits 0. An extractor that raises, times out, or finds a file it cannot parse becomes an `unknowns` entry carrying the error text, and the rest of the envelope is still produced. If the audit itself cannot start, the envelope is `{"status": "audit_unavailable", "reason": ...}` and the caller proceeds as if no audit existed. The card renderer, the author renderer, and the inspect integration all treat a missing or unavailable audit as "no card", never as an error.

**Low latency, parallel.** Extractors are independent and run as a fan-out: frontmatter, each body file, deps.toml, disk inventory, and one task per adapter, each with its own timeout. Correlation runs once when the fan-out converges. Budget is one second for a Play in the local store on a warm cache and three seconds cold. Adapter metadata is cached by fingerprint, package extraction by digest, host facts per host and digest.

**Persisted, by Play id, with history.** Every envelope is written under Play's home, `PLAY_HOME` or `~/.play`, and is retrievable later without re-running. See Persistence and history.

**Read everything, execute nothing at pull time.** Adapter reads through `rote adapter info` and `rote registry adapter info` are metadata reads and are the only subprocesses the audit runs. The Play's own code is never executed.

**Silence never reads as clean.** Rules that could not run and bodies that could not be read are named, on both surfaces, as unknowns rather than omitted.

**Nothing reaches a consumer that is not a fact.**

## Accuracy: no false positives by construction

A wrong finding costs more than a missed one. Three mechanisms enforce precision.

**Facts versus judgments.** Every rule is classed at authoring time. A *fact* is provable from the package alone: a referenced resource is not shipped, a step's command is absent from deps.toml, `parameters:` sits under `metadata:`, a step has no `timeout_ms`, a `depends_on` names an unknown step, a Python resource uses a construct CPython's own feature table rejects at the declared floor, the frontmatter and generated manifest disagree, a literal spawned command is undeclared, a step names an operation its adapter does not expose. A *judgment* needs context the package does not carry: a bare `find` will hit a protected folder, a parameter is unused, a `sed -i` is BSD or GNU. Judgments ship to authors only, marked as judgments, with the reasoning shown.

**Corpus-measured precision.** Before a rule ships, it runs over every public Play in the registry and each hit is labelled by hand. A fact rule must score 100 percent or it is reclassified as a judgment. A judgment ships only above 90 percent and carries its measured precision in the report. The sweep reruns on every rule change and registry sync; a rule that drifts below its bar is demoted automatically.

**Fixtures and suppression.** Every rule has a positive and a negative fixture, and the negative fixture is the case that fooled the rule last time. An author can mark a finding as intended in frontmatter, `audit.allow: [{rule, reason}]`, and the reason is shown wherever the rule would have fired. Suppressions are visible to the author, never to the consumer.

## What is correlated

ast-grep is an extractor, not the analysis. It matches one file at a time. The driver builds the package picture from five inputs and every fact comes from a pair of them.

Inputs: frontmatter (steps, argv, for_each, depends_on, parameters, requires_endpoints, adapter_sources, execution_model, writes, fixtures); bodies via ast-grep (presentation, legacy body, every `.py` and `.sh` resource, inline `sh -c` and `python3 -c` strings lifted from argv); deps.toml; the package on disk (resources, fixtures, generated manifest); adapters (`rote adapter info <id> --json` for the installed copy, `rote registry adapter info <owner>/<id> --json` for the pinned source).

Pairs: steps versus deps; bodies versus deps; bodies versus the deps floor; steps versus disk; frontmatter versus manifest; frontmatter versus body; parameters versus every reader; steps versus adapter (operation exists, auth requirement matches, write guard agrees); pinned adapter source versus installed copy (fingerprint and provenance, the #2181 collision, reported to a consumer as one sentence about this machine).

## Author hygiene: directed feedback

The author surface is a work order, not a lint dump.

**Every finding names its owner.**

| Class | Owner skill |
|---|---|
| Frontmatter, parameters, DAG shape, deps.toml, resources, fixtures | rote-flow-authoring |
| Failure contract, exit status, partial traversal, resume | rote-troubleshooting |
| Shell and command patterns, portability, bashisms | rote-shell |
| Presentation body, truncation handling, body reach | rote-typescript-transformations |
| Publication, visibility, adapter pinning | rote-registry |

**Every finding carries a fix packet.** Location as file and line or a frontmatter path such as `steps.find.argv[0]`, the recipe in prose, a mechanical patch when one exists, the rote command when one applies, and the fixture that proves the fix.

**The author chooses what to send.** After an audit, Play presents the open findings and the author picks which to hand off, all, some, or none. The chosen packets go to rote-troubleshooting through the existing delegated-action handoff, which diagnoses, delegates the edit to the owner skill, and reports back what changed with a run reference. Nothing is sent without the author's choice, and the audit never edits a Play itself.

**Improvement is recorded.** When rote-troubleshooting reports back, the audit reruns on the edited package and writes a new envelope. The history entry records which findings closed, which remain, anything new, the handoff run reference, and the package digest before and after. The author sees a delta, never a fresh full report. The registry inbox report, when the author opts in, carries the same delta so a consumer who reported an issue sees it close.

**Release rehearsal.** Before `rote play release`, Play renders the Play as three consumers would see it, from host profiles rather than the author's machine: stock macOS with only the command line tools, Ubuntu LTS, and the author's own host. For each profile the author sees the exact report card, per-step readiness, and the first sentence a consumer would read if something blocks. Rehearsal informs; release remains the author's call.

## Consumer report card

Shown after the inspect disclosure and before the run prompt. Plain text, one screen, the same voice as the rest of Play. It is a map of the Play, not a verdict on it, and it never delays or prevents the prompt.

In order: **Shape** (steps in execution order with their kind, one line each); **Reach** (commands run here, services called and whether they need sign-in, files read, writes declared, where supplied parameters flow); **Needs from this machine** (each required tool with the version found against the version declared, in words); **What to expect** (at most three sentences drawn only from facts, phrased as expectations); **Can it run here** (one line: yes, or the single reason it may not and the install hint).

Never shown: rule ids, severities, counts, judgments, suppressions, or anything phrased as a problem with the author's work. Unknowns are stated: a step whose body could not be read appears in Reach as "runs code this inspection could not read". If the audit was unavailable, the card is simply absent.

## Persistence and history

Layout under `PLAY_HOME`, default `~/.play`:

```
~/.play/audit/
  plays/<owner>/<name>/
    index.json                 latest envelope per version, by digest
    <version>/<digest>.json    one envelope per package digest per host profile
    history.jsonl              append-only: audits, handoffs, deltas
  adapters/<fingerprint>.json  cached adapter metadata
  hosts/<host-id>.json         cached host facts
  corpus/                      labelled hits and precision per rule
```

`play-audit history <reference>` lists the timeline for a Play: each audit with its digest, open fact count, unknown count, the handoffs sent and what they closed. `play-audit show <reference> [--at <digest>]` renders any past envelope. History is what lets a consumer's report and an author's fix meet on the same record, and what lets the corpus tooling learn from labelled outcomes.

Writes are atomic and best-effort. A write failure is logged into the envelope's unknowns and never raised.

## Report contract

Envelope `play-audit/1`, one analysis, four renderings. Sections: subject (reference, version, package digest, rote version, time), host (live or named profile), shape, needs, facts, judgments (author only, with precision), unknowns (unread bodies, skipped rules, failed extractors with error text), suppressions (author only), history_ref.

Renderings: `--card` (consumer, default inside inspect), `--author`, `--json`, `--report` (Markdown for the registry inbox, with digest). Exit code is always 0. Callers read `summary.open_facts` if they want a number; nothing in Play branches on it.

## Architecture

- `scripts/lib/play/audit/`: `runner.py` (fan-out with per-task timeouts, converge, fail-safe wrapper), `frontmatter.py`, `package.py`, `steps.py`, `bodies.py` (ast-grep rules over TypeScript, Python, shell, YAML), `adapters.py` (metadata reads, fingerprint cache), `host.py` and `profiles/`, `correlate.py`, `rules/` (YAML rules with class, owner, fixtures, measured precision), `store.py` (persistence and history), `card.py`, `author.py`, `report.py`.
- `scripts/bin/play-audit <path|reference> [--card|--author|--json|--report] [--profile <name>]`, plus `history` and `show` subcommands.
- Engine: `ast-grep-py` pinned in pyproject and uv.lock. In the no-uv fallback the AST rules are skipped and listed as unknowns.
- Sidecar `.rote-audit.json` beside the installed Play remains an option for rote's search to read; the store under `~/.play` is authoritative.
- Corpus tooling under `scripts/audit-corpus/`.

## Rules, first cut, by class

Facts: PARAMETERS_UNDER_METADATA, BODY_STRANDED, DEPS_TOML_MISSING, TOOL_UNDECLARED, RESOURCE_MISSING, FIXTURE_MISSING, MANIFEST_DRIFT, DEPENDS_ON_UNKNOWN, STEP_NO_TIMEOUT, INTERPRETER_FLOOR_MISSING, PY_FLOOR_TOO_LOW, INLINE_CODE_PAYLOAD, FANOUT_OVER_PREVIEW, DENO_COMMAND_UNDECLARED, CHILD_PROCESS_UNDECLARED, SUBPROCESS_UNDECLARED, ROTE_EXEC_UNDECLARED, ABSOLUTE_HOME_PATH, ADAPTER_OPERATION_UNKNOWN, ADAPTER_AUTH_MISMATCH, ADAPTER_SOURCE_PROVENANCE_DIFFERS.

Judgments: PARAM_UNREFERENCED, TOOL_DECLARED_UNUSED, UNRELIABLE_EXIT_STATUS, PIPEFAIL_PROPAGATES, BASHISM_IN_SH, MACOS_ONLY_COMMAND, LINUX_ONLY_COMMAND, BSD_GNU_FLAG, COREUTILS_ABSENT_ON_MACOS, DYNAMIC_COMMAND_UNRESOLVABLE, PRESENTATION_READS_PREVIEW_IGNORES_TRUNCATED.

Unknowns, never findings: INLINE_BODY_UNREAD, ADAPTER_NOT_READABLE, EXTRACTOR_FAILED.

## Integration points

1. **inspect_registry_play**, before run. The audit runs in the fan-out alongside inspect; the card is appended to the disclosure when ready, or omitted if unavailable. The run prompt is never delayed past the budget or withheld.
2. **prepare_candidate**, at crystallization. The audit runs on the candidate and its author view is offered so the authoring skill starts from a clean shape.
3. **author_release**, before `rote play release`. Release rehearsal renders the profiles and the author view. The author chooses what to hand off. Release proceeds regardless.
4. **smoke_publication**, after publish. The card as published is attached to the receipt and the birth certificate, and the envelope is written to history with the publication reference.
5. **Feedback loop.** Author: choose findings, hand off to rote-troubleshooting, receive the report-back, re-audit, record the delta. Consumer who is not the author: `--report` to the registry inbox with the digest, opt-in.

## Milestones

1. Runner, contract, facts, card, store (week 1). Fan-out runner with fail-safe wrapper, envelope, rule classes, fact rules with fixtures, card renderer, persistence and history, `play-audit` with `history` and `show`. Card inside `play-inspect` behind a flag.
2. Corpus and precision (week 2). Registry sweep, hand-labelled hits, precision per rule, CI bar. Judgment rules land only after clearing it. Portability rules get their first real positives from the corpus or stay unshipped.
3. Author hygiene and adapters (week 3). Owner mapping, fix packets, author choice, rote-troubleshooting handoff and report-back, delta recording, adapter correlation, host profiles, release rehearsal.
4. Loop and upstream (week 4). Inbox report with deltas, receipt attachment, card on by default in inspect. First fact rules upstreamed to rote lint as ast-grep rule files.

## Risks

- A judgment leaking onto the consumer card. The card renderer reads only the facts section, enforced by a test that renders a fixture containing every judgment and asserts none appear.
- The audit slowing inspect. Hard per-task timeouts, the fan-out budget, and the rule that a late audit is omitted rather than awaited.
- An audit failure surfacing as an inspect failure. The fail-safe wrapper is tested with every extractor forced to raise, and inspect must still render.
- Corpus labelling cost. Label once per rule per registry sync; hits are few.
- Duplicating rote lint. Import its sidecar, add only what it lacks, upstream facts.

## Decisions to make

- Whether the sidecar beside the install is written at all, or `~/.play` is the only store.
- Whether the consumer's inbox report is opt-in per Play or per session.
- Which host profiles ship first, and whether Windows is a third.

## Evidence base

- Issues https://github.com/modiqo/rote/issues/2177 through 2181.
- Prototype scanner and ast-grep rules from the 2026-09-03 session: 49 findings over 13 Plays, verified against the Plays behind the issues with negative controls.
