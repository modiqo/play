# Play Management Views

Use this guidance for `$play list orgs`, `$play orgs`, `$play list plays`, `$play plays`, and
equivalent organization or Play inventory requests. These are read-only management operations; do
not route them through Play search or Explore.

## Resolve the view

- `org_summary`: list every organization authorized for the current identity with active member,
  private Play, public Play, and total Play counts.
- `plays_by_org`: list all authorized Plays grouped first by organization and then by Private and
  Public visibility.
- If the request names a view, run it without another question. If the user says only `$play list`
  or otherwise leaves the view ambiguous, use the `select_management_views` multi-select prompt.

## Collect once and aggregate

`rote play list` covers local Plays, while organization-aware inventory requires registry reads.
Prefer the bundled `scripts/bin/play-inventory <orgs|plays|all>` command for the combined view. It
does not persist registry responses:

1. Run `rote registry org list --json` once.
2. Run `rote registry play list --mine --json` once and retain only organizations returned by the
   authorized organization list.
3. For `org_summary`, run `rote registry org members <slug> --json` once per organization. Parallel
   independent member reads when the harness supports it.
4. Count only active members. Count each non-deleted Play once by its reported `visibility`.

Fail closed on malformed JSON, an unknown visibility, an organization whose member list cannot be
read, or an inventory item that cannot be assigned to an authorized organization. Do not invent
zeroes or include member identities when only counts were requested.

## Present cleanly

For `org_summary`, render one compact table sorted by organization name:

| Organization | Members | Private | Public | Total |
|---|---:|---:|---:|---:|

For `plays_by_org`, sort organizations and Play names alphabetically. Under each organization show
its total, then separate `Private (N)` and `Public (N)` lists. Render `— None` for an empty group.
Keep descriptions out of the default inventory so a large organization remains scannable; inspect
one Play only when the user asks for its details.
