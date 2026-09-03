/**
 * @rote-frontmatter
 * ---
 * name: partial-scan
 * description: Find dirty repos
 * metadata:
 *   version: 0.1.0
 *   execution_model: steps_with_presentation
 * parameters:
 * - name: base_folder
 *   type: string
 *   required: true
 * steps:
 *   find:
 *     type: process.exec
 *     argv:
 *     - find
 *     - $base_folder
 *     - -name
 *     - .git
 *   check:
 *     type: process.exec
 *     depends_on:
 *     - find
 *     for_each: .stdout.text | split("\n")
 *     argv:
 *     - git
 *     - -C
 *     - $item
 *     - status
 *     timeout_ms: 3000
 * ---
 */
const sdk = await import("__ROTE_PRESENTATION_SDK__");
const { FlowOutput, loadPresentationContext, stepName } = sdk;
const out = new FlowOutput();
const ctx = await loadPresentationContext();
const s = ctx.step(stepName("check"));
const body: any = s.outcome.status === "completed" ? s.outcome.output.body : [];
const lines = (Array.isArray(body) ? body : [body]).map((b: any) => b?.stdout?.text ?? "");
out.human(lines.join("\n")); out.summary("done"); out.result({ lines });
