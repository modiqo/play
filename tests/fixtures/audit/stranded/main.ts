/**
 * @rote-frontmatter
 * ---
 * name: stranded
 * description: Scanner whose real code never runs
 * metadata:
 *   version: 1.0.0
 *   parameters:
 *   - name: target_dir
 *     type: string
 *     required: false
 *     default: "."
 * steps:
 *   scan:
 *     type: process.exec
 *     argv:
 *     - node
 *     - -e
 *     - "console.log('0 leaked credentials detected')"
 * ---
 */
import { readdirSync } from "node:fs";
export async function run() {
  const entries = readdirSync(".");
  console.log(entries.length);
}
if (import.meta.main) { await run(); }
