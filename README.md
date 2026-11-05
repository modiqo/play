# Play

**Reuse work that already works, without giving up visibility or control.**

Play runs on [rote](https://getrote.dev). Ask your agent for an outcome with `/play` (`$play` in
Codex). rote checks whether a saved Play already produces it. If one fits, you see what it does and
approve the exact run. If none fits, your agent explores the task in a rote workspace, and rote
offers to save the result as a Play for next time.

This repository holds what makes rote behave like Play:

- `pack/`: Play's rote journey pack. rote's journey engine runs every step from it.
- `SKILL.md`: the `/play` skill. It hands the request to `rote journey next` and follows rote's
  yields. rote's root skill and `rote guidance` own everything else.
- `play recurring`: schedules a Play through [Tulving](https://github.com/modiqo/tulving).
- The journey viewer and the Play audit, as developer tooling.

## Install

Install rote with the Play pack:

```sh
curl -fsSL https://getrote.dev/install | bash -s -- --pack play
```

`ROTE_PACK=play` does the same as `--pack play`. After rote's own setup, the script installs the
Tulving runtime, installs the `play` journey pack that rote pins, and runs `rote harness setup`.
That writes rote's skill and its prompt hook line for Claude Code and Codex. Codex asks you to trust
the hook once before it runs it. Cursor gets no hook line, so use `/play` there.

The `/play` skill comes from this repository's plugin marketplace:

```sh
codex plugin marketplace add modiqo/play
codex plugin add play@play-skills

claude plugin marketplace add modiqo/play
claude plugin install play@play-skills
```

Restart your agent afterwards so it loads the skill.

## The journey pack

`pack/pack.ron` builds on rote's baseline `entry`, `run`, `explore`, and `publish` journeys:

| Setting | What it does |
| --- | --- |
| `entry: "entry"` | `rote journey next` starts at rote's entry journey, which judges whether the request runs, creates, or publishes a Play |
| `hooks` | The `UserPromptSubmit` hook ticks the entry journey for each prompt, inside rote's 3 s hook cap |
| `slots.run.BeforeApprove` | The agent judges whether the inspected Play does what the user asked. A Play that does not fit enters `explore` instead of asking for approval |
| `search.worker_url` | Registry search uses Play's judged-search Worker until rote's own Worker at `search.getrote.dev` is live |
| `requires_rote` | The first rote release with these journeys and settings |

`pack/copy/*.ftl` rewords some of rote's prompts in Play's voice. Each message replaces rote's
baseline message with the same id.

`pack/transcripts/` holds one `<name>.events.ron` sim fixture and its expected `<name>.trace.json`
per path: a run with approval, a near-match pick, a Play judged not relevant, a no-match that
enters explore, and a create that is saved locally. rote's `play-compat` job lints the pack and
replays every transcript on each rote change, so rote cannot break Play silently.

```sh
just pack-check            # lint the pack and replay the transcripts
just pack-traces           # rewrite the traces after an intended rote change
ROTE=/path/to/rote just pack-check   # try a development build of rote
```

Both recipes run in a throwaway `ROTE_HOME`.

## Recurring Plays

Recurring work is optional and needs Tulving's clock. Schedules pin the exact Play version and its
parameters, record a reason, and default to a 30-day lifetime.

```sh
play recurring probe
play schedule --reference modiqo/check-registry@1.2.3 \
  --cadence daily --why "Notice registry changes" --for 30d \
  --parameter org=modiqo
```

`play recurring` checks the parameters against the Play's declared inputs with `rote play
inspect`, validates the schedule with Tulving, and refuses a duplicate of an active schedule.
`play recurring --help` lists the other commands: `list`, `recall`, `last`, `now`, `stop`,
`snooze`, `status`, `clock on|off`, `export`, and `update`. Play reads structured schedule data
through a private `tulving mcp` subprocess; it registers no MCP server in any harness.

## Developer tooling

- `play journey live` opens the journey viewer for the active rote workspace. See
  [docs/journey-viewer.md](docs/journey-viewer.md).
- `play audit <play URI|path>` prints an advisory report card for a Play. `play-audit-corpus`
  measures the audit against published Plays.

## Development

```sh
uv sync
npm ci
just test        # pyright, viewer tests, plugin package check, typos, unit tests
just package     # copy SKILL.md into the plugin and sync versions from VERSION
```

Releases are tagged from `VERSION`; see [docs/releases.md](docs/releases.md).
