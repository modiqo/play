# Play cheat sheet

Play helps you find, inspect, run, and save reusable procedures. It always shows the method and
declared effects before asking whether to run it.

Use the invocation your app supports:

| App | Play prefix |
|---|---|
| Codex or Cursor | `$play` |
| Claude Code, Hermes, OpenCode, or DeepSeek Harness | `/play` |
| Kimi Code | `/skill:play` |

The examples below use `$play`; substitute your app's prefix. Plain `play cheat-sheet` shows this
page in every supported app.

## Get started for the first time

```text
You:  run the Play installer
Setup: verifies Rote, offers Google or GitHub when sign-in/account creation is needed,
       then caches a verified public Play catalog before activating your agent apps
You:  start the agent and type $play
Play: verifies the post-login setup, reads What’s New locally, then offers the low-risk Hello Play
You:  choose Run Hello
Play: shows the exact method, inputs, credentials by name, and declared effects
You:  approve the run
Play: returns the verified result and receipt
```

The normal installer finishes sign-in before touching Play-owned harness state. If a session later
expires or is revoked, Play’s harness recovery lane guides sign-in and resumes the original
request. An empty `$play` is also the safest way to check or repair setup.

## Find and run an existing Play

```text
You:  $play run the PostHog daily active users report
Play: searches local and authorized catalogs, then shows the best matching cards
You:  choose a card
Play: inspects the exact version and asks separately for run approval
You:  approve the run
Play: Rote executes it and returns the primary result plus a receipt
```

Useful forms:

```text
$play find a Play that retrieves recent emails
$play search live status for AI services
$play run the PostHog daily active users report
$play https://play.modiqo.ai/<owner>/<name>
```

An exact reference or URI skips search, but never skips inspection or approval.

## See what is available

```text
You:  $play what's new
Play: shows new or revised Plays in your authorized scope and a labeled public sample
You:  choose a domain, then a Play
Play: inspects that Play before offering a run
```

```text
$play what's new
$play digest
$play list orgs
$play list plays
$play list
```

`$play list` asks which inventory views you want; the more specific forms run immediately.

## Turn successful work into a Play

```text
You:  $play create a reusable weekly customer report
Play: searches first; if nothing adequate exists, it classifies the work before it starts
Play: for reusable work, returns a capture handle and a Rote workspace
Agent: completes and verifies the work through that workspace
You:  $play settle cap_xxxxxxxxxxxxxxxx built and verified the weekly report
Play: checks the captured trace and, only if worth saving, offers Team, Community, or Skip
```

```text
$play create a reusable <outcome>
$play settle <capture-handle> <what was verified>
```

Settling works only for a handle created before the work. Normal or uncaptured work cannot be
retrofitted into a Play.

## See how a Play was made

```text
You:  $play birth weekly customer report
Play: shows the owner-local, redacted birth certificate and its evidence summary
```

```text
$play birth <name-or-reference>
$play show how <owner>/<name> was born
```

Birth certificates exclude raw commands, parameters, responses, credentials, and workspace paths.

## Work directly for one request

```text
You:  direct: deploy this Worker with wrangler
Play: stays out of this request
Agent: uses the appropriate CLI or API directly
```

```text
direct: <request>
without play: <request>
```

This is a one-turn bypass. It does not become a sticky mode and does not bypass harness
permissions, credentials, tool approvals, or safety checks.

## Route a provider directly in this project

```text
You (chat):     Initialize Play routing for this repo
Play:           creates `.play/routing.yaml`, or reports that the existing policy is current

You (terminal): play-routing --project . add cloudflare-direct \
                  --provider cloudflare --tool wrangler \
                  --executor api --executor cli
You (chat):     deploy the Worker with Cloudflare
Play:           the prompt hook stays silent for the matching action request
Agent:          uses an allowed API or CLI path directly
```

You can manage policy conversationally:

```text
Initialize Play routing for this repo
Route GitHub directly through gh in this project
Show this project's Play routing policy
Stop routing GitHub directly here
```

Without an explicit scope, Play defaults to the current repository. Say “globally”, “user policy”,
or “all projects” to manage the owner-private user policy instead. These requests use the routing
CLI directly and never enter the Play state machine.

Manage project routes:

```text
play-routing --project . init
play-routing --project . add github-direct \
  --provider github --provider github-actions --tool git --tool gh \
  --executor api --executor cli
play-routing --project . list
play-routing --project . list --json
play-routing --project . remove github-direct
```

Manage routes across all projects by replacing `--project .` with `--user`. Running `add` again
with the same route ID updates it. Install creates an empty owner-private user policy; project
policy lives at `.play/routing.yaml`, and the nearest policy inside the Git worktree is used.

A routing policy is not an executor or a permission override. It only prevents Play activation for
matching action requests; the harness still chooses and authorizes the actual API or CLI operation.
Malformed policies authorize nothing. There is deliberately no sticky `$play skip` mode: use
`direct:` once, or a narrow user/project route when the preference should persist.
