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
 * presentation_fixtures:
 *   count: resources/presentation-fixtures/count/fixture.yaml
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
if (step.outcome.status !== "completed" && step.outcome.status !== "restored") {
  const reason = step.outcome.status === "blocked" ? "blocked by an upstream failure" : "the count step failed";
  out.human(`count unavailable: ${reason}`);
  out.summary("count unavailable");
  out.result({ text: null, partial: false, unavailable: reason });
} else {
  const body: any = step.outcome.output.body;
  const text = body?.stdout?.text ?? "";
  const partial = body?.stdout?.truncated === true;
  out.human(`${text}${partial ? " (partial: output was truncated at 64 KiB)" : ""}`);
  out.summary(partial ? "counted (partial)" : "counted");
  out.result({ text, partial });
}
