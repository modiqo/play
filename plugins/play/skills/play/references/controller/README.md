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
