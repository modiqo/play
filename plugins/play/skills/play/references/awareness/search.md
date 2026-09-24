# Play Search

Use `scripts/bin/play-search <query> --json` for outcome discovery and omit `--json` for
user-facing results. Explicit search, Explore discovery, and the passive prompt hook share the
Cloudflare search Worker. Only published Plays are candidates; local drafts and cached catalogs
never supply relevance results.

## Preserve the request and its constraints

The client preserves natural wording, negation, and quoted constraints. It redacts concrete URLs,
email addresses, paths, handles, dates, and recognizable credential assignments. Requests outside
3–400 characters fail with an actionable error; the client never truncates away exclusions.

The controller passes `request.intent` as the query and `request.original` with `--also`. The
original wording takes precedence. A paraphrase cannot turn “audit without changing records” into
a request for a repair Play. Lexical helpers remain available for authoring tag hints only.

## Search published groups through the Worker

Play calls the existing Cloudflare search Worker over HTTPS. For authenticated searches,
`rote whoami --check` refreshes the login first. Play reads the resulting access token from
Rote's private registry configuration and sends it only to the matching production or staging
Worker. It never prints or persists a token. Public searches send no credentials.
Accessible scope requires sign-in and never silently falls back to public scope.
No custom Rote command or binary is required.

The Worker searches community, personal, and currently accessible organizations. Use `--public` for
community only or `--org <slug>` for one organization. Authorization remains server-side. The
Worker retrieves registry candidates, judges intent with Jev, and returns groups with direct,
partial, and uncertain or unverified matches. No client lexical score can promote a rejected Play.

The client checks the response contract, published identity, exact URI, visibility, scope, and
bounded result lists. Search-only requests display groups and mark uncertain matches separately.
A direct judgment maps to full coverage; partial and unverified results cannot trigger full-match
handling. Results retain `owner/name@version` for subsequent inspection and execution.

## Preserve incomplete search evidence

Timeouts and transport errors fail explicitly. Omitted organizations, retrieval failures,
truncation, degraded judgment, and incomplete judgment keep `complete: false`. Useful verified
matches can still be inspected. Empty incomplete results never authorize a conclusion that no
suitable Play exists, including on the Explore creator path.

Explore can issue up to three additional sub-outcome queries. Each retains the whole request and
its constraints and uses the same Worker. An incomplete or skipped sub-query keeps the overall
search incomplete. There is no local, cached-catalog, or raw registry fallback.

## Keep suggestions passive

The prompt hook searches only action-shaped requests with a three-second deadline. A direct
judgment may produce one quiet suggestion, even if an unrelated group was truncated. Uncertain,
partial, degraded, failed, and timed-out searches stay silent. The hook never runs a Play or starts
the controller. Explicit user selection still requires inspection and the existing execution
approval rules.

Local execution and browsing remain separate from discovery. Inspection determines whether the
published version is installed and whether a pull or other local change requires consent.
