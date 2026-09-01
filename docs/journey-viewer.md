# Journey viewer guide

Journey turns a Rote exploration trace into a world that can be traversed in time. It does not
anthropomorphize the agent from the outside. It places you at the agent's vantage, inside the
situation in which it operated, so intent, tools, effects, evidence, and recovery can be understood
spatially.

The experience is an homage to the spatial legibility of Doom, Wolfenstein 3D, and Halo: movement,
landmarks, and time teach the world. Journey borrows that idea, not those games' visual style.

This guide explains how to launch and read the viewer. For implementation and schema details, see
the [asynchronous Journey design](design/async-exploration-journey-graph.md) and the
[world-model reference](design/journey-world-model-v2.md).

## Launch Journey

After installing Play, open the most relevant active Rote exploration:

```bash
play-journey view --active
```

From a source checkout, the equivalent command is:

```bash
./scripts/bin/play-journey view --active
```

Journey first synchronizes with the Rote workspace containing the current directory when one is
available; otherwise it uses Rote's most recently updated workspace. It then replaces any older
Journey server and opens one owner-private loopback viewer on `127.0.0.1:52050`.

Useful variants:

```bash
play-journey view --capture cap_xxxxxxxxxxxxxxxx  # Open one capture
play-journey view --active --no-open              # Print the URL without opening it
play-journey view --active --port 52100           # Override the singleton port
play-journey view --active --json                  # Return launch metadata as JSON
```

`PLAY_JOURNEY_PORT` can set the port without adding `--port` to every invocation.

## Start Here

A first launch begins with the deterministic **Start Here** tutorial, even if a live exploration
exists. Read the short orientation, open **Read the World Model**, then choose **Enter the Vantage**
to replay one mixed-modality example. The tutorial creates and verifies a Notion page through
CALL, SHELL, and DRIVE so each primitive is learned in context.

An explicit workspace link opens that workspace instead. After the tutorial, use **Journeys** to
choose another workspace.

## Follow and Atlas

Journey has two complementary views of the same projection:

| View | Use it for | What it shows |
|---|---|---|
| **Follow** | Experiencing the trace as an embodied route | A stable chase view of one road, semantic infrastructure, upcoming stages, and a fixed evidence HUD |
| **Atlas** | Understanding the whole route | A compact aerial terrain with the same sites, chronology, interaction clusters, and evidence links |

Follow is the primary replay experience. Atlas is the cartographic overview; it is not a second
truth model. Select a district in Atlas to inspect it, or press **Play** to follow the journey's
progress through the aerial terrain. The former Audit view was removed because its graph overview
duplicated Atlas without adding a clearer user task. The canonical graph is still preserved in the
Journey store.

## Read the world model

A site is a semantic vantage, not a command. Its landmark answers *why this part of the journey
exists*. The interactions situated at that site answer *what happened there*.

| Primitive | Spatial role | Plain-English meaning | Running example |
|---|---|---|---|
| Intent | Starting gate | Fixes the outcome before a route is chosen | Create a page in Notion |
| Decision | Fork in the road | Records a choice between valid routes | Choose Notion CALL, browser DRIVE, or `notion-cli` SHELL |
| Capability | Station | Equips and initializes a system before use | Initialize the Notion adapter |
| Authority | Checkpoint | Requires authentication, permission, or approval | Authorize the Notion workspace |
| Phase | Journey chamber | Groups supporting operations serving one purpose | Prepare the page title, body, and parent ID |
| Effect | Worksite | Changes or retrieves the outside world | Create the page through Notion |
| Evidence | Observatory | Checks what actually happened | Open the page and verify its title and body |
| Artifact | Destination | Delivers a durable result | Return the verified page URL |
| Blocker | Barricade | Keeps an obstruction visible | Creation fails because the parent database is unavailable |
| Recovery | Bridge | Reconnects the agent to a valid route | Find the correct database and retry |
| Milestone | Monument | Marks an achievement worth remembering | The verified page now exists |
| Learning | Knowledge marker | Preserves an insight for later journeys | Remember the database ID and required properties |
| Play candidate | Reusable blueprint | Shapes verified work into a reusable procedure | Draft a reusable verified-page route |
| Play | Published gateway | Makes that procedure available to a later journey | Release the verified Notion-page Play |

Open **World Model** at any time to see this vocabulary. Follow turns each primitive into road
infrastructure: decisions become junctions, authority becomes a barrier, and phases become gates.

## Capabilities, modalities, and operations

Journey keeps four ideas separate:

1. A site's **semantic role** says why the step exists.
2. A **capability instance** is the actual system the agent equipped and initialized.
3. Its **modality** says how the agent operated it.
4. **Operations** are the ordered actions performed through that capability.

The three Rote modalities are:

| Rote modality | Capability family | Examples |
|---|---|---|
| **CALL** | adapter/API | Notion, GitHub, ElevenLabs, and other typed adapters |
| **SHELL** | proc | `git`, `rg`, tests, PTYs, streams, and background leases |
| **DRIVE** | browser | Page leases, snapshots, lenses, actions, waits, and ref rebases |

A capability is discovered or initialized first, authorized when required, and only then used or
observed. Journey shows the lifecycle supported by the trace; it does not invent a probe, login, or
approval that Rote did not record. Operation names and arguments also cannot manufacture access or
safety claims. Effect posture comes from typed adapter contracts, process policy, and browser
ledger primitives; absent typed evidence remains **unknown**.

## Read interactions and time

Follow renders recorded interactions as constant-sized detected objects near the current stage.
The fixed HUD keeps every operation readable while the road moves. Each exchange shows its
canonical `@N`, capability, access posture, status, and a request → response affordance.

Select an exchange to open the evidence panel. The panel shows typed capability, lifecycle,
access, timing, tokens, and redacted request/response data when Rote recorded it. Scale no longer
encodes telemetry because large foreground geometry obscures the route and weakens comparison.

An **Evidence unavailable** message means the source trace has no displayable exchange at that
reference, it was redacted, or its owner-private evidence is no longer present. Journey never
copies raw credentials, sensitive parameters, or response bodies into its semantic graph.

## Replay live and recorded workspaces

Selecting any workspace starts at its first site, ready to play.

- **Recorded** is a fixed trace and replays from the beginning.
- **Live · updating** has a recent Rote heartbeat and may receive new sites.
- **Live · quiet** can still grow but has not recorded a recent command.
- **Workspace snapshot** has Rote evidence but no matching active Play capture.

Press **Play** for a historical replay. Select **Track live** or the blinking live endpoint to move
to the active head and follow calm, coalesced snapshots. Scrubbing, freezing a vantage, or opening
evidence releases live tracking so refreshes do not pull the camera away from what you are reading.

Long explorations keep the interface bounded: the tracker projects representative semantic
markers, the renderer materializes a local window rather than the whole history, and every
canonical stage remains reachable through the scrubber. This changes presentation density, not
the stored graph.

## Read model telemetry

The unobtrusive telemetry ticket advances with replay. **Site** is the aggregate for operations at
the current vantage; **Journey** is the cumulative trace through that vantage. It reports captured
input/output tokens, estimated cost, operation count, successes, errors, and estimated context
consumption.

Model identity is read from the Rote workspace when recorded. Otherwise Journey uses the local
default. Installation creates owner-editable configuration and a cached pricing/context catalog:

```text
~/.play/model-config.yaml
~/.play/cache/model_prices_and_context_window.json
```

Cost is an estimated lower bound based on captured tool I/O and the cached LiteLLM catalog, not a
provider invoice. Context and compaction percentages are likewise estimates until the trace records
an observed compaction boundary. Hidden reasoning and unrecorded conversation are not invented.

## Controls

- Use **Play** to follow the road or **Freeze** to hold the current stage.
- Select a recorded exchange in the fixed Follow HUD to inspect its evidence.
- Use the bottom scrubber or semantic markers to jump through a long journey.
- Use **Fit** in Atlas to restore the complete aerial framing.
- Use **Refresh** to request a coherent snapshot without changing a frozen vantage.

## Troubleshooting

### “There is no active captured exploration”

Run the command from inside the active Rote workspace, confirm that the exploration has started,
or open a known capture with `--capture`. Current installations synchronize with Rote before
resolving `--active`; an older installed CLI should be reinstalled or updated from this repository.

### The viewer opened the wrong workspace

Use **Journeys** to select the workspace explicitly, launch from within the desired workspace, or
open it by capture handle. A URL containing an explicit workspace selection takes precedence over
the Start Here default.

### The viewer is not advancing

Recorded workspaces do not grow. For a live workspace, select **Track live**. A frozen vantage or
open evidence inspection intentionally holds position while newer snapshots are projected.

### The displayed model or price is wrong

Inspect `~/.play/model-config.yaml`. Workspace-recorded model identity wins by default; the file can
provide model-family, effort, pricing-model, context-window, and compaction-threshold overrides.
The pricing catalog is an install-time cache and can lag upstream pricing.

### Evidence is missing

The viewer is a disposable projection over Rote's owner-private evidence. Confirm the source
workspace still exists under `~/.rote/workspaces`, then rebuild the projection if necessary. Play falls back to
the legacy `~/.rote/rote/workspaces` root when the current root has no workspaces. If both roots
contain workspaces, Play uses the current root and prints a warning.

Missing or redacted evidence is reported honestly rather than reconstructed from labels.
