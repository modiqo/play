import assert from 'node:assert/strict'
import test from 'node:test'
import {buildExchangeTree, formatByteSize, initialOpenIds, previewOf, visibleRows} from './exchange-tree.mjs'

const payload = {
  method: 'messages.list',
  auth: {token: 'Bearer [REDACTED]', scopes: ['read']},
  items: [{id: 1, body: 'x'.repeat(200)}, {id: 2}],
}

test('rows are depth first with kinds, counts, and byte sizes', () => {
  const tree = buildExchangeTree(payload)
  const root = tree.rows[0]
  assert.equal(root.kind, 'object')
  assert.equal(root.count, 3)
  assert.ok(root.bytes > 200)
  const ids = tree.rows.map((row) => row.id)
  assert.deepEqual(ids.slice(0, 4), ['$', '$/method', '$/auth', '$/auth/token'])
  assert.equal(tree.rows.find((row) => row.id === '$/items').kind, 'array')
})

test('redacted values are flagged and counted', () => {
  const tree = buildExchangeTree(payload)
  assert.equal(tree.redactedCount, 1)
  assert.ok(tree.rows.find((row) => row.id === '$/auth/token').redacted)
})

test('long strings preview with an ellipsis and null reads as null', () => {
  assert.equal(previewOf('x'.repeat(200)).length, 96)
  assert.equal(previewOf(null), 'null')
  assert.equal(previewOf(42), '42')
})

test('containers open to the default depth and folding hides descendants', () => {
  const tree = buildExchangeTree(payload)
  const open = initialOpenIds(tree.rows)
  assert.ok(open.has('$') && open.has('$/auth') && open.has('$/items'))
  assert.ok(!open.has('$/items/0'))
  const shown = visibleRows(tree.rows, open)
  assert.ok(shown.some((row) => row.id === '$/items/0'))
  assert.ok(!shown.some((row) => row.id === '$/items/0/body'))
  open.delete('$/auth')
  const folded = visibleRows(tree.rows, open)
  assert.ok(!folded.some((row) => row.id === '$/auth/token'))
})

test('byte sizes format for humans', () => {
  assert.equal(formatByteSize(512), '512 B')
  assert.equal(formatByteSize(2048), '2.0 KB')
  assert.equal(formatByteSize(3 * 1024 * 1024), '3.0 MB')
})

test('a null payload still yields one row', () => {
  const tree = buildExchangeTree(null)
  assert.equal(tree.rows.length, 1)
  assert.equal(tree.rows[0].kind, 'null')
})
