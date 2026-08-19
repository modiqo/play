# Play cheat sheet

> Find a Play. Run it safely. Step out when you want. Turn your expertise into the next Play.

Play is designed to weave into and out of the same agent session. Ask naturally when you want a
reusable procedure, use a direct lane when you do not, and let Play remember only the moments that
are worth turning into shared know-how.

## Pick your path

| I want to… | Start with… | What happens |
|---|---|---|
| Try Play for the first time | `$play` | Guided setup, then the low-risk Hello Play |
| Get something done | Ask in English | The hook checks the cached catalog and activates Play only for a strong match |
| Run a specific Play | `$play https://play.modiqo.ai/<owner>/<name>` | Search is skipped; inspection and approval are not |
| Browse what is available | `$play what's new` | A fast catalog digest and a random sample of up to 10 current public Plays |
| Recall today's Play journeys | `$play journal` | A private daily command log of matches, selections, approved runs, completions, and blockers |
| Bypass Play and Rote once | `direct: <request>` | The whole turn uses harness-native tools or the vendor CLI/API directly |
| Keep a provider direct here | `Route GitHub directly through gh in this project` | A narrow `.play/routing.yaml` rule is created or updated |
| Create a reusable procedure | `$play create a reusable <outcome>` | Play searches first, then captures new work only when it may be reusable |
| See how a Play was made | `$play birth <name-or-reference>` | A redacted, provenance-preserving birth certificate |
| Open this page | `play cheat-sheet` | The deterministic cheat sheet—no search or state machine |

## Use the prefix your app understands

| App | Play prefix |
|---|---|
| Codex or Cursor | `$play` |
| Claude Code, Hermes, OpenCode, or DeepSeek Harness | `/play` |
| Kimi Code | `/skill:play` |

The examples below use `$play`; substitute your app’s prefix. You often do not need a prefix at all:
an ordinary request can activate Play when the local cached catalog contains a strong match.

## Your first minute: become a Playrunner

```text
You:   $play
Play:  checks post-login setup and offers Run Hello
You:   Run Hello
Play:  shows the exact method, inputs, credentials by name, and declared effects
You:   Pull and run
Play:  prints the complete result and its verified receipt
Hook:  🎭 Playrunner unlocked
```

Hello is the safest proof: public data, no account credentials, and no declared writes. After the
first successful run, Play teaches the next useful move instead of sending you to a manual.

```text
$play run hello
```

## Ask for an outcome, not a command

```text
You:   can you retrieve my rideshare receipts between July 15 and August 15, 2026?
Hook:  finds modiqo/retrieve-rideshare-receipts in the cached catalog
Play:  inspects the exact version and normalizes the dates to the Play’s declared format
Play:  shows Gmail access, parameters, setup, and effects
You:   Pull and run
Play:  authenticates if needed, runs the approved version, and prints the receipts
```

Play should reuse parameters already present in your request. It asks only for values that are
genuinely missing, ambiguous, or invalid according to the Play’s frontmatter.

Useful forms:

```text
retrieve recent emails
list top committers for modiqo/rote
$play find a Play that checks calendar meetings
$play run the PostHog daily active users report
$play https://play.modiqo.ai/modiqo/retrieve-recent-emails query="newer_than:1d"
```

An exact URI skips discovery. It never skips inspection, parameter validation, or run approval.

## Know what “Pull and run” means

```text
Play:  Ready to run modiqo/example@1.2.3 with the displayed parameters and effects?

       Pull and run — install or replace that exact version, then execute it
       Not now      — stop without installing, authenticating, or running anything
```

Choosing a search result is permission to inspect it—not permission to execute it. The run always
has its own approval boundary.

## See what’s new without waiting around

```text
You:   $play what's new
Play:  reads the install-warmed catalog cache
Play:  shows new or revised items plus a random sample of up to 10 current public Plays
You:   choose one, search by outcome, create your own, or leave
```

```text
$play what's new
$play digest
$play list orgs
$play list plays
$play list
```

What’s New is a fast deterministic path: no full preflight and no narrated continuation machinery.
The cache refreshes in bounded background/install flows rather than making every request pay for it.

## Recall what you ran today

```text
You:   $play journal
Play:  reads the owner-private command log
Play:  shows today's matched, selected, approved, completed, and blocked Play journeys
```

```text
$play journal
$play journal yesterday
$play journal 2026-08-17
```

The journal is built from successful state-machine transitions, not reconstructed from chat. It
stores only the run ID, canonical Play reference, lifecycle event, timestamp, and local day—never
your prompt, parameters, output, credentials, continuation ID, or workspace path. Repeated
observation of the same run stage is deduplicated. Opening it is a fast local read with no registry
search, preflight, or continuation.

## Step out for one whole turn

Sometimes you want the agent—not Play and not Rote—to use the native tool or vendor CLI/API.

```text
You:   direct: deploy this Worker with wrangler
Hook:  marks the entire turn as a Play-and-Rote bypass
Agent: uses harness-native tools or the Cloudflare CLI/API directly
```

```text
direct: <request>
without play: <request>
```

The bypass covers inference continuations, delegation, retries, and tool loops for that user turn.
It is not sticky: your next ordinary request can use Play again. It also does not bypass harness
permissions, authentication, tool approvals, or safety checks.

## Keep GitHub or Cloudflare direct in one repository

Use a narrow routing policy when a provider should consistently skip both Play and Rote in this
project.

```text
You:   Initialize Play routing for this repo
Play:  creates .play/routing.yaml, or reports that it is already current

You:   Route GitHub directly through gh in this project
Play:  adds github-direct with the stated provider and tool

You:   check the GitHub Actions run for this branch
Hook:  injects the matched direct-route constraints
Agent: uses an allowed harness-native or GitHub API/CLI path
```

Manage it conversationally:

```text
Initialize Play routing for this repo
Route GitHub directly through gh in this project
Route Cloudflare directly through wrangler in this project
Show this project's Play routing policy
Stop routing GitHub directly here
```

Or manage it from the terminal:

```sh
play-routing --project . init

play-routing --project . add github-direct \
  --provider github --provider github-actions \
  --tool git --tool gh \
  --executor api --executor cli

play-routing --project . list
play-routing --project . remove github-direct
```

Replace `--project .` with `--user` only when the route should apply across projects. A routing
policy chooses an orchestration lane; it is not a permission override or an executor.

## Authenticate without putting secrets in chat

Play has two user-facing authentication paths.

### Browser sign-in: OAuth, Google, and DCR

When a Play declares `adapter.auth.ensure`, authentication belongs to the Play run itself.

```text
You:   Pull and run
Play:  opens the provider’s secure browser authorization
You:   approve access in the browser
Play:  verifies the named credential and continues the same approved run
```

The harness should not ask you to paste an OAuth credential, build an authentication receipt by
hand, or restart the request after successful browser authorization.

### Static tokens: create and store them out of band

A Play can detect a missing vendor token, but it cannot mint one for you.

```text
Play:      GitHub authentication needs GITHUB_TOKEN
Play:      shows GitHub’s verified first-party token page
Your shell: rote token set GITHUB_TOKEN --stdin
You:       choose “I've set it — verify and retry”
Play:      compares the adapter manifest key with the exact name in `rote token list --json`
Play:      retries the exact approved run only when that named credential is healthy
```

Useful checks:

```sh
rote token list
rote token set GITHUB_TOKEN --stdin
```

Paste the token into your own terminal command—never into chat. Play verifies credential metadata,
not the secret value. If the exact key is still missing or unhealthy, no provider call is started.

## Keep the result visible

The primary result is the point of the run. Play prints it before moving on.

```text
Play:  <complete primary result>
Play:  <verified receipt>
Hook:  <event-backed nudge, when one was earned>
```

If your harness truncates a long result, choose **Show result again**. Play retrieves the preserved
full output instead of summarizing it away or asking the next question before you can see it.

## Follow the nudges: Playrunner → Playmaker

Nudges are earned by successful Play events, not by every ordinary assistant message.

| Event | What you unlock | The useful next move |
|---|---|---|
| First successful Play | 🎭 **Playrunner** | Run another Play by URI or plain-English outcome |
| Later successful Plays | 🎭 **Play complete** | Try another outcome or save a reusable improvement |
| Create a reusable Play | 🛠️ **Playmaker** | Test it with a real edge case |
| Share privately | 🤝 **Team Playmaker** | Ask a teammate to run it and add domain feedback |
| Publish publicly | 🌍 **Community Playmaker** | Help people discover it by outcome and adapter |

Every completed Play receives an event-backed nudge. Duplicate observation of the same run does not
produce duplicate noise.

## Turn your expertise into a Play

```text
You:   $play create a reusable weekly customer report
Play:  searches existing Plays first
Play:  finds no adequate match and classifies the work before execution
Play:  creates a capture handle and Rote workspace for reusable work
Agent: works through the captured path
You:   guide the agent—correct assumptions, name stages, and test edge cases
Agent: verifies a clean repeatable result
You:   $play settle cap_xxxxxxxxxxxxxxxx built and verified the weekly report
Play:  checks the captured evidence, then offers Team, Community, or Skip
```

Your expertise matters while the Play is forming. A good captured path has distinct stages, inputs
that can vary on reuse, a stable output, and a verified happy-path rerun.

During active captured exploration, Play occasionally shows **Exploration progress** derived from
the Rote workspace journal: new steps, successes and errors, operation latency, payload tokens,
cached-query savings, recent trajectory nodes, and dependency edges. It waits for five new steps
and at least two minutes after the previous pulse, so it teaches progress without narrating every
tool call. These statistics never appear during ordinary work or while running an existing Play.
Use `direct: <task>` for a one-turn side-step without closing the capture, then say
`continue exploration` to return. Direct work stays outside the saved trajectory until Play
revalidates any state it changed.

```text
$play create a reusable <outcome>
$play settle <capture-handle> <what was verified>
```

Settling is intentionally not retrospective: it works only with the owner-private capture handle
created before the work began.

## Share it—or keep it yours

```text
Team       publish privately to an authorized organization
Community  publish under an eligible public owner and verify the public artifact
Skip       keep the result without publishing or indexing a Play
```

Nothing becomes public merely because it was created. Publication has its own explicit choice and
verification path.

## See the provenance, not the secrets

```text
$play birth weekly customer report
$play birth modiqo/retrieve-recent-emails
$play show how modiqo/retrieve-recent-emails was born
```

Birth certificates preserve how the Play came to exist while excluding raw commands, parameters,
responses, credentials, and workspace paths.

## Pocket card

```text
$play                                      # Guided start
$play run hello                            # Low-risk first run
$play what's new                          # Fast cached catalog digest
$play journal                             # Today's deterministic recall command log
$play journal yesterday                   # A previous local day
$play find a Play that <does something>   # Search by outcome
$play https://play.modiqo.ai/<owner>/<name>
$play create a reusable <outcome>          # Search first, then capture if warranted
$play settle <capture-handle> <summary>    # Re-enter a verified capture
$play birth <name-or-reference>            # Show provenance
$play list                                 # Browse authorized inventories
play cheat-sheet                           # Open this page

direct: <request>                          # Bypass Play + Rote for one whole turn
without play: <request>                    # Equivalent spelling
play-routing --project . list              # Show persistent direct routes here

rote token list                            # Show credential names and health, not values
rote token set <ENV_VAR> --stdin           # Store a static token outside chat
```

## The three rules worth remembering

1. **Inspect before you approve.** A match is not permission to run.
2. **Secrets stay out of chat.** Browser authorization stays in the Play; static tokens go through
   `rote token set … --stdin` in your terminal.
3. **Choose your lane.** Ask naturally for Play, use `direct:` for one whole turn, or add a narrow
   routing policy when a provider should remain direct in a project.
