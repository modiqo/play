/**
 * @rote-frontmatter
 * ---
 * name: pyfloor
 * description: Needs a newer Python than it declares
 * metadata:
 *   version: 0.1.0
 *   execution_model: steps_with_presentation
 * parameters:
 * - name: repo
 *   type: string
 *   required: true
 * steps:
 *   check:
 *     type: process.exec
 *     argv:
 *     - python3
 *     - '@resource{check.py}'
 *     - $repo
 *     timeout_ms: 5000
 * ---
 */
const sdk = await import("__ROTE_PRESENTATION_SDK__");
const { FlowOutput, loadPresentationContext } = sdk;
const out = new FlowOutput();
const ctx = await loadPresentationContext();
out.human(String(ctx.params.repo)); out.summary("ok"); out.result({});
