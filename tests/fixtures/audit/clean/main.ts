/**
 * @rote-frontmatter
 * ---
 * name: clean
 * description: A well-formed Play
 * metadata:
 *   version: 1.0.0
 *   status: released
 *   kind: atomic
 *   flow_type: sequential
 *   execution_model: steps_with_presentation
 * parameters:
 * - name: repo
 *   type: string
 *   required: true
 * steps:
 *   count:
 *     type: process.exec
 *     argv:
 *     - sh
 *     - '@resource{count.sh}'
 *     - $repo
 *     timeout_ms: 5000
 * ---
 */
const sdk = await import("__ROTE_PRESENTATION_SDK__");
const { FlowOutput, loadPresentationContext, stepName } = sdk;
const out = new FlowOutput();
const ctx = await loadPresentationContext();
const step = ctx.step(stepName("count"));
const body: any = step.outcome.status === "completed" ? step.outcome.output.body : null;
const text = body?.stdout?.text ?? "";
const partial = body?.stdout?.truncated === true;
out.human(`${text}${partial ? " (partial)" : ""}`);
out.summary("counted");
out.result({ text, partial });
