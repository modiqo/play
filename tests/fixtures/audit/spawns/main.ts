/**
 * @rote-frontmatter
 * ---
 * name: spawns
 * description: Spawns commands from code
 * metadata:
 *   version: 0.1.0
 *   execution_model: steps_with_presentation
 * parameters: []
 * steps:
 *   probe:
 *     type: process.exec
 *     argv:
 *     - python3
 *     - '@resource{probe.py}'
 *     timeout_ms: 5000
 * ---
 */
const cmd = new Deno.Command("gh", { args: ["auth", "status"] });
const which = Deno.env.get("TOOL") ?? "ls";
const dynamic = new Deno.Command(which, { args: [] });
const sdk = await import("__ROTE_PRESENTATION_SDK__");
const { FlowOutput } = sdk; const out = new FlowOutput(); out.human("x"); out.summary("x"); out.result({ cmd, dynamic });
