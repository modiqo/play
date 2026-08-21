import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import test from 'node:test'

const css = readFileSync(new URL('../journey_viewer/viewer.css', import.meta.url), 'utf8')

test('telemetry uses feathered smoked glass without blurring its text layer', () => {
  const counter = css.match(/\.model-live-counter \{(?<body>[\s\S]*?)\n\}/)?.groups?.body || ''
  const smoke = css.match(/\.model-live-counter::before \{(?<body>[\s\S]*?)\n\}/)?.groups?.body || ''

  assert.match(counter, /isolation: isolate/)
  assert.match(counter, /text-shadow: 0 1px 1px/)
  assert.doesNotMatch(counter, /filter:\s*drop-shadow/)
  assert.match(smoke, /backdrop-filter: blur\(14px\) saturate\(\.6\) brightness\(\.5\)/)
  assert.match(smoke, /mask-image: linear-gradient/)
  assert.match(smoke, /transparent 100%/)
})
