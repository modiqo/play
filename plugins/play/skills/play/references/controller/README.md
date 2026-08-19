# Play controller contracts

This directory is the executable documentation for Play's deterministic controller.

| File | Authority |
|---|---|
| [`machine.yaml`](machine.yaml) | States, owners, checkpoints, transitions, guards, and mutations. |
| [`actions.yaml`](actions.yaml) | Deterministic/model/specialist actions and their closed event contracts. |
| [`prompts.yaml`](prompts.yaml) | Human questions, choices, and typed payload requirements. |
| [`context.schema.json`](context.schema.json) | Complete `play.context/v1` state carried by a run. |
| [`handoff.schema.json`](handoff.schema.json) | Specialist and saved-Play handoff packets and receipts. |
| [`machine.schema.json`](machine.schema.json) | Declarative-machine syntax. |
| [`command-log.md`](command-log.md) | Transition-derived recall journal and pre-machine command routing. |
| [`command-log.schema.json`](command-log.schema.json) | Durable `play.recall-journal/v1` storage contract. |

`scripts/bin/validate-machine` validates the bundle before packaging. `play-machine describe
--json` reports the compiled bundle SHA and state counts. `scripts/bin/package-plugin --check`
ensures every controller contract shipped in the plugin is byte-for-byte current.

The command log is an observer, not another state machine. It consumes only successful transitions
after context validation and cannot select a target, mutate controller context, authorize an
effect, or prevent a Play from completing. Presentation also stays outside the transition loop:
captured exploration pulses are claimed by the Stop hook, while the daily recall journal is shown
only when the user asks for it.

An approved empty-search exploration is not a terminal standby. `record_standby` creates the
capture and workspace, then `capture_is_active` routes through the visible `exploration_begin`
phase to `exploration_execute`. That delegated state invokes the `rote` entrypoint with the
unchanged outcome and completed no-match evidence.
Rote owns all nested routing: `rote-task-routing` runs explore/inventory/catalog gates,
`rote-adapter-create` adapts an accepted API, `rote-shell` validates and records an accepted CLI,
and `rote-workspace` executes adapter work. Play accepts only a complete result plus a verified,
capture-bound workspace trajectory before entering verification and save judgment.

Every accepted event projection includes both a prebound `event_template` and a self-contained
`payload_schema` with exact types, enums, and object shapes. Harnesses and specialists must fill
the template according to that schema instead of guessing metadata values.

Captured exploration distinguishes prerequisites from outcomes. Adapter setup, authentication,
token verification, capability probes, and smoke tests return `exploration_prerequisite_ready`
when they must cross a boundary; the machine then resumes the original exploration without
entering verification or save judgment. Only useful outcome-bearing work may return
`exploration_outcome_ready`.

The exploration-only journey surface deterministically presents start, prerequisite-ready,
route-recovery, verified-completion, and one-off-completion phases. Tool discovery stays inside the
Rote specialist, which must present alternatives, retain an “another tool” choice, verify the
selected route, and wait before execution. A `direct:` turn leaves the Play continuation and Rote
workspace paused; it is not captured evidence and `continue exploration` resumes only after changed
external state is revalidated.
