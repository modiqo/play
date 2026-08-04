# JUDGE

JUDGE is an optional Flow node for irreducible inference. It is not a general exploration
modality, and the Play controller's bounded decisions are not JUDGE steps.

Preserve a JUDGE node only when all of these are true:

- deterministic CALL, SHELL, DRIVE, and transformation steps cannot reproduce the decision;
- the decision is necessary to achieve or verify the outcome;
- the input can be expressed as a stable structured contract;
- the output can be validated against a stable structured contract;
- `judge_policy.allowed` is true.

Otherwise encode deterministic rules, assertions, filters, or transformations.

## Contract

Represent a JUDGE step as a Flow-controlled shell invocation of a configurable agent harness such
as Claude, Codex, or Kimi. The Flow owns:

- the structured input schema and populated input;
- the selected harness and allowed configuration;
- the structured output schema;
- timeout, retry, and failure behavior;
- output validation and evidence capture.

Treat free-form prose, missing required fields, schema violations, or an unavailable configured
harness as a failed node. Never infer a valid result from surrounding narration. Do not silently
substitute another harness.

Keep the JUDGE step narrow. Deterministic steps before it should prepare the smallest sufficient
input; deterministic steps after it should validate and apply the result. Record why inference was
irreducible so a future author can replace it when a deterministic method becomes available.
