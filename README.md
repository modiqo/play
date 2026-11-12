# Play

Play is a journey pack for [rote](https://getrote.dev). It is also the example to copy when you
build your own pack.

rote does all the work. Its baseline journeys route each prompt, search for a saved Play, check
that the Play fits the request, ask for approval, run it, and offer to save new work as a Play. A
pack changes only what it names. This one rewords some of rote's prompts and points registry
search at Play's judged-search Worker.

## Install

Install rote with this pack:

```sh
curl -fsSL https://getrote.dev/install | bash -s -- --pack play
```

If rote is already installed, run `rote install play`. Both install the release of this pack that
rote pins. To install a local checkout instead:

```sh
rote journey pack install ./pack
```

Then run `rote harness setup` and restart your agent.

## What is in a pack

```text
pack/
  pack.ron          the pack: id, schema, the rote it needs, and the settings it changes
  copy/journey.ftl  wording that replaces rote's baseline prompts, by message id
  transcripts/      sim fixtures: <name>.events.ron and the trace rote must produce
```

`pack/pack.ron`:

| Setting | What it does |
| --- | --- |
| `id`, `schema` | Name the pack and its format, `rote.pack/v1` |
| `requires_rote` | The oldest rote that can run the pack |
| `search.worker_url` | Registry search uses Play's judged-search Worker until rote's own Worker at `search.getrote.dev` is live |

`pack/copy/journey.ftl` replaces rote's message with the same id. An attribute you leave out keeps
rote's text, and an id rote does not define fails lint.

A pack can also replace or add journeys, fill the slots a baseline journey declares, change the
prompt hook, and change other settings. Run `rote guidance journey/packs` for the full list.

## Check the pack

Each `pack/transcripts/<name>.events.ron` replays through `rote journey sim` and must produce
`<name>.trace.json`. rote's `play-compat` job lints this pack and replays every transcript on each
rote change, so rote cannot break the pack silently.

```sh
just check                           # spelling, release scripts, tarball build
just pack-check                      # lint the pack and replay the transcripts
just pack-traces                     # rewrite the traces after an intended rote change
ROTE=/path/to/rote just pack-check   # use a development build of rote
```

The pack recipes run in a throwaway `ROTE_HOME`.

## Releases

Releases are tagged from `VERSION`, and each release publishes the pack tarball that rote pins.
See [docs/releases.md](docs/releases.md).
