# Play Birth Certificates

A birth certificate is the owner’s private, one-time account of how a released Flow emerged from an
exploration workspace. Play owns this incubating feature; Rote core and the registry do not store or
serve it.

## Lifecycle

After a candidate becomes a released Flow and before its first Private or Public publication, run:

```bash
scripts/bin/play-birth capture --workspace <workspace> --flow <released-flow> --json
```

Capture is idempotent by the released Flow artifact fingerprint. Repeating it returns the existing
birth SHA without recapturing workspace evidence. A materially different released artifact gets a
different fingerprint and certificate.

After publication mints the canonical version, bind the immutable object to the registry identity:

```bash
scripts/bin/play-birth bind <birth-sha-or-selector> --reference <owner/name>@<version> --json
```

Binding confirms the exact registry version, content hash, and publication author provenance when
the immutable registry metadata supplies it. It updates only the local index; it
never mutates the content-addressed birth object. Bind before local Playcard indexing, then continue
with the normal canonical inspection readback. The birth output is not the terminal publication
readout: after verified readback, Public must still present the registry-returned Play page and
install/bootstrap URIs plus paste-ready X and LinkedIn copy through the typed certificate renderer.

After matching canonical readback—and, for Public, credential and smoke verification—render the
bound certificate with:

```bash
scripts/bin/play-certificate --stdin --json
```

The controller context on stdin supplies verified publication metadata and the safe human handle;
the renderer independently reads the owner-local immutable birth object. It fails closed when the
birth SHA, exact reference, or registry content hash differs. Its visualization includes redacted
trace successes, errors, and unknown outcomes, the public Play URI and share copy when applicable,
and the personalized closing. It never posts social copy or exposes raw trace content.

## Private storage

The declared store is independent of Rote:

```text
~/.play/births/
  objects/<birth-sha256>.json
  index.json
```

`PLAY_HOME` or `--home` may override the root for tests or an explicitly managed installation.
Directories are mode `0700`, files are mode `0600`, writes are atomic, and index updates are locked.
“Owner-only” currently means the local OS user. The certificate does not follow a pulled Play to a
different machine and is not available to organization members or the public. Migrating this store
is a separate, explicit user operation.

This store is not Play controller context. Store only the immutable birth record and its lookup
bindings; never add consent, pending actions, harness state, credentials, registry payloads, or
execution results.

## Evidence and privacy

Prefer `rote trace --deps --json` when Rote exposes it. Until then, the helper recognizes that
specific capability gap and falls back to `rote workspace inspect log --json` plus
`rote workspace inspect deps --json`. Other trace failures block capture instead of silently
downgrading evidence.

The birth object stores only:

- safe released-Flow metadata and hashes of portable package members;
- workspace name, command/response/variable totals, timing, execution mode, and token savings;
- command-type and dependency-type counts, safe numeric dependency edges, inferred modalities,
  and explicit success/error/unknown command-outcome counts;
- the evidence methods used and explicit privacy exclusions.

The binding index adds only exact references, registry content hashes, and publication author
provenance. An unavailable author remains explicitly unavailable; Play never infers identity from
an owner slug or the current login.

Never store workspace paths, raw commands, parameters, queries, responses, response contents,
variable names, dependency field paths, credentials, or environment data.

## Retrieval

Interpret `$play birth <name-or-reference>` and natural requests such as “show how this Play was
born” as owner-local birth lookup. Use:

```bash
scripts/bin/play-birth show <name|owner/name@version|birth-sha> --json
scripts/bin/play-birth list --json
scripts/bin/play-birth verify <selector> --json
```

Name lookup must resolve to exactly one local certificate. If it is absent, say that no owner-local
birth certificate is available; do not query the registry as if it possessed one. If it is
ambiguous, present the matching birth SHA prefixes or exact references and ask the user to choose.
