# RCA: GitHub adapter token-env mismatch broke public Play run

- **Date of incident:** 2026-08-06
- **Artifact:** `chetan/list-my-github-repos` (public registry push)
- **Status:** Remediated — adapter republished as `chetan/github@1.1.0` using `GITHUB_API_TOKEN`; Play republished as `chetan/list-my-github-repos@0.0.2`; public URI now resolves and runs
- **Severity:** Medium — no data loss or security impact; a public consumer running the advertised URI hit a credential-resolution error

## Summary

A Play that lists repositories for the authenticated GitHub user was published to the public registry and appeared healthy (`play_run_eligible: true`), but running it via the first-class surface failed because the Play's declared adapter source expected a different token environment variable than the user had configured locally.

The local `github` adapter was authenticated with `GITHUB_API_TOKEN`. The Play was first pushed with `metadata.adapter_sources` pointing to `theelilap/github`, whose manifest declares `token_env: GH_TOKEN`. Running `rote play run https://play.modiqo.ai/chetan/list-my-github-repos@0.0.1 --yes` failed with:

```
error: Play credential `GH_TOKEN` for adapter `github` is missing;
  run `rote token set GH_TOKEN --stdin` as the manual fallback, then retry
```

After republishing the local adapter as `chetan/github` and rebinding the Play to it, a second issue appeared: the installed adapter's provenance no longer matched the approved candidate, requiring `rote registry adapter pull chetan/github --yes`. That pull replaced local auth configuration and again expected `GH_TOKEN`, so the adapter auth was updated to `GITHUB_API_TOKEN`, the adapter was bumped and republished, backup files from the earlier adapter transaction were cleaned up, and the public Play finally ran end-to-end.

## Impact

- `chetan/list-my-github-repos@0.0.1` was publicly available but not runnable for anyone using `GITHUB_API_TOKEN` (including the author).
- The author had to publish a second adapter version (`chetan/github@1.1.0`) and a second Play version (`chetan/list-my-github-repos@0.0.2`) to fix the mismatch.
- Trust cost: the public Play was congratulated before it had been smoke-tested through `rote play run <public-uri>`.

## Timeline (2026-08-06)

1. User set `GITHUB_API_TOKEN` for the locally installed `github` adapter; local adapter health showed `static_unverified` but healthy.
2. Play `list-my-github-repos` was authored, linted, tested locally, and released.
3. First registry push selected `theelilap/github` as the adapter source because its fingerprint matched the local adapter; push succeeded and returned `play_run_eligible: true`.
4. User asked to run the public URI. `rote play run <uri> --yes` failed with missing `GH_TOKEN`.
5. Local `github` adapter was published as `chetan/github@1.0.0`; Play adapter source updated to `chetan/github`; Play bumped to `0.0.2` and republished.
6. Running the new URI failed because installed adapter provenance (`theelilap/github`) no longer matched the approved candidate (`chetan/github`).
7. `rote registry adapter pull chetan/github --yes` installed the published adapter, but its manifest declared `GH_TOKEN`, so local health flipped to `static_missing`.
8. `rote adapter auth update github --bearer-token GITHUB_API_TOKEN` restored the desired token env var.
9. Adapter was bumped to `1.1.0` and republished as `chetan/github@1.1.0`.
10. Residual backup files blocked adapter resolution; backups were removed.
11. `rote play run https://play.modiqo.ai/chetan/list-my-github-repos@0.0.2 --yes` succeeded.

## Root causes

1. **Adapter auth env var is part of the published adapter contract.** Two adapters with the same fingerprint can declare different `token_env` values. The Play's `metadata.adapter_sources` field binds a specific published adapter, and that binding determines which env var the consumer must set.
2. **Local adapter provenance was not aligned with the declared source.** The local adapter had been installed from `theelilap/github` but was later republished under `chetan/github`; rote correctly refused to resolve the Play until the installed adapter provenance matched the declared source.
3. **Process failure (proximate cause).** The Play was congratulated and shared after registry push succeeded, but it was never smoke-tested through the public `rote play run <uri>` surface before being announced.
4. **No pre-publication adapter-source review.** The registry selected `theelilap/github` automatically based on fingerprint matching; the mismatch in `token_env` was not surfaced until runtime.

## Remediation

| # | Action | Status |
|---|--------|--------|
| R1 | Republish local `github` adapter as `chetan/github@1.1.0` with `token_env: GITHUB_API_TOKEN` | Done |
| R2 | Update Play `metadata.adapter_sources` to `chetan/github`; bump and republish Play as `chetan/list-my-github-repos@0.0.2` | Done |
| R3 | Clean up stale adapter backup files blocking resolution | Done |
| R4 | Smoke-test the public URI with `rote play run https://play.modiqo.ai/chetan/list-my-github-repos@0.0.2 --yes` | Done |
| R5 | **Process gate:** before congratulating/sharing a public Play, always run `rote play run <public-uri> --yes` (or with explicit parameters) from a clean `/tmp` directory | Done in Play 0.1.3 |
| R6 | **Adapter-source check:** after push, compare the exact Play resolver, installed adapter, and selected registry adapter across provenance, version, fingerprint, auth family, and credential names | Done in Play 0.1.3 |
| R7 | **Secret boundary:** retain credential names and bounded evidence only; never inspect or persist credential values or the smoke run's primary payload | Done in Play 0.1.3 |

## Prevention: checks before the next public Play

Play 0.1.3 now enforces these checks before announcing a public Play that depends on an adapter:

1. Run `rote play run <public-uri> --yes` from `/tmp` (no local workspace context).
2. Verify the adapter source and credential contract the registry resolved:
   ```bash
   rote play inspect <public-uri> --json
   rote adapter info <adapter> --json
   rote registry adapter info <owner>/<adapter> --json
   ```
   The Play controller performs and compares these reads through
   `scripts/bin/play-publication-gate credentials --stdin --json`.
3. Confirm the required token env var matches what the author/local user has configured.
4. If the local adapter uses a different `token_env`, either:
   - republish the adapter under the author's namespace with the matching `token_env`, or
   - ask the user to set the token env var declared by the selected adapter source.

## Lessons

- A registry push returning `play_run_eligible: true` is necessary but not sufficient; the public URI must be exercised through the exact command a consumer would run.
- Adapter fingerprint matching does not imply identical runtime configuration. `token_env` (and other auth metadata) is part of the adapter contract and must be reviewed when binding a Play to a published adapter.
- Republishing an adapter under a new owner changes provenance; consumers must pull the new source before the Play can resolve.
- Leftover adapter backup files can block resolution after a failed adapter transaction; they should be cleaned up before retrying.
