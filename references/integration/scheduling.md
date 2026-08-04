# Harness Scheduling and Delivery

Use this guidance when a user asks for a recurring Play digest or when an authorized harness
scheduler invokes Play. Scheduling, destination authorization, delivery, and durable checkpoint
storage belong to the host. Play owns digest collection and the portable delivery contract.

## Discover capability

Run `scripts/bin/play-scheduler-probe`. It performs read-only `--help` probes and reports
`play.scheduler-capabilities/v1`.

- `native` means the harness exposes a recurring scheduler command. Use that host capability.
- `unavailable` means the harness is installed but exposes no recognized recurring scheduler.
- `not_installed` and `probe_failed` are blockers, not permission to install software or invent a
  cron, launchd, background process, database, or checkpoint file.
- An external scheduler skill may implement the contract only when it is already authorized or the
  user explicitly approves installing and configuring it.

Do not infer scheduler support from marketing language, background-agent support, one-shot remote
execution, or an option description containing words such as automation.

## Prepare once

At the scheduled time, the host invokes:

```text
scripts/bin/play-delivery prepare \
  --target-key <opaque-destination-key> \
  --channel <host-channel> \
  --checkpoint <host-owned-checkpoint.json>
```

If there is no checkpoint yet, omit `--checkpoint` and select the initial window with `--days` or
`--since`. The result is an immutable `play.digest-delivery/v1` envelope containing:

- a deterministic `delivery_id` that is the idempotency key;
- the structured digest and rendered Markdown message;
- update and public-Play counts;
- a proposed `play.digest-checkpoint/v1` checkpoint held behind a success acknowledgment.

The host must retain and retry the same envelope after a transient send failure. Running `prepare`
again creates a later window end and is a new delivery attempt, not an idempotent retry.

## Deliver, acknowledge, release

The host delivers `message.body` to the authorized target. After confirmed success, it creates:

```json
{
  "schema": "play.digest-delivery-ack/v1",
  "delivery_id": "<exact envelope delivery_id>",
  "status": "delivered"
}
```

It then invokes:

```text
scripts/bin/play-delivery release --envelope <envelope.json> --ack <ack.json>
```

`release` emits the exact checkpoint object the host may persist. It never writes the checkpoint.
It rejects failed, malformed, or mismatched acknowledgments. The host must persist only the output
of a successful release, keyed by identity, authorized organization scope, schedule, and target.

This ordering guarantees at-least-once delivery with an idempotency key:

```text
load checkpoint -> prepare -> deliver -> acknowledge -> release -> host persists checkpoint
                                     failure -> checkpoint remains unchanged
```

## Preserve boundaries

- Never put credentials, email addresses, or channel secrets in `target_key`; use an opaque host
  identifier.
- Re-authorize organization access on every digest collection. A checkpoint carries time only and
  grants no registry scope.
- Let the host own timezone and recurrence. Digest windows and checkpoints are UTC instants.
- A missed run naturally catches up from the last successfully released checkpoint.
- Do not claim exactly-once delivery. Hosts can provide it only if their destination honors the
  deterministic `delivery_id` as an idempotency key.

