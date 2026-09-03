/**
 * @rote-frontmatter
 * ---
 * name: missing-resource
 * description: References a script it does not ship
 * metadata:
 *   version: 0.1.0
 *   execution_model: steps_with_presentation
 * parameters: []
 * steps:
 *   run:
 *     type: process.exec
 *     depends_on:
 *     - prepare
 *     argv:
 *     - sh
 *     - '@resource{run.sh}'
 *     - /Users/someone/project
 *     timeout_ms: 5000
 * ---
 */
const sdk = await import("__ROTE_PRESENTATION_SDK__");
const { FlowOutput } = sdk; const out = new FlowOutput(); out.human("x"); out.summary("x"); out.result({});
