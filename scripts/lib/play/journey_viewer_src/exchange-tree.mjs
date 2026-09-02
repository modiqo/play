/**
 * Tree projection of a redacted exchange payload for the visor pane.
 *
 * Pure: turns request or response JSON into rows with depth, kind, size, and
 * redaction flags, so the pane can fold, colour, and measure without ever
 * re-parsing the payload during render.
 */

export const REDACTED_MARK = '[REDACTED]'
export const DEFAULT_OPEN_DEPTH = 2

export function formatByteSize(bytes) {
  const size = Math.max(0, Number(bytes) || 0)
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(size < 10240 ? 1 : 0)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function kindOf(value) {
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'array'
  return typeof value
}

function isRedacted(value) {
  return typeof value === 'string' && value.includes(REDACTED_MARK)
}

export function payloadBytes(value) {
  try {
    return new TextEncoder().encode(JSON.stringify(value ?? null)).length
  } catch {
    return 0
  }
}

/** Depth-first rows; containers carry their child count and byte size. */
export function buildExchangeTree(value, {openDepth = DEFAULT_OPEN_DEPTH} = {}) {
  const rows = []
  let redactedCount = 0
  const walk = (node, key, depth, path) => {
    const kind = kindOf(node)
    const container = kind === 'object' || kind === 'array'
    const entries = container ? (kind === 'array' ? node.map((item, index) => [String(index), item]) : Object.entries(node)) : []
    const redacted = isRedacted(node)
    if (redacted) redactedCount += 1
    rows.push({
      id: path,
      key,
      depth,
      kind,
      container,
      count: entries.length,
      bytes: payloadBytes(node),
      open: container && depth < openDepth,
      redacted,
      preview: container ? null : previewOf(node),
    })
    for (const [childKey, childValue] of entries) walk(childValue, childKey, depth + 1, `${path}/${childKey}`)
  }
  walk(value ?? null, '', 0, '$')
  return {rows, redactedCount, bytes: payloadBytes(value)}
}

export function previewOf(value) {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'string') {
    const single = value.replace(/\s+/g, ' ')
    return single.length > 96 ? `"${single.slice(0, 93)}…"` : `"${single}"`
  }
  return String(value)
}

/** Rows visible under a set of open container ids. */
export function visibleRows(rows, openIds) {
  const visible = []
  let hideBelow = null
  for (const row of rows) {
    if (hideBelow !== null) {
      if (row.depth > hideBelow) continue
      hideBelow = null
    }
    visible.push(row)
    if (row.container && !openIds.has(row.id)) hideBelow = row.depth
  }
  return visible
}

export function initialOpenIds(rows) {
  return new Set(rows.filter((row) => row.open).map((row) => row.id))
}
