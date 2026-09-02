import React, {useEffect, useMemo, useRef, useState} from 'react'
import {formatNumber} from './format.js'
import {buildExchangeTree, formatByteSize, initialOpenIds, visibleRows} from './exchange-tree.mjs'
import {exchangeFlowMs, stepSequence, visorChips} from './visor-layout.mjs'

/**
 * The windshield visor: recorded exchanges docked as holographic chips, each
 * tethered to its bead in the lane, and one unfolded pane for the selected
 * exchange. Geometry decisions live in `visor-layout.mjs`; this file paints.
 */

function useViewportWidth() {
  const [width, setWidth] = useState(() => window.innerWidth)
  useEffect(() => {
    const update = () => setWidth(window.innerWidth)
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])
  return width
}

function Gauge({sweep, size = 18, className = ''}) {
  const radius = 7
  const circumference = 2 * Math.PI * radius
  return <svg className={`hud-gauge ${className}`} viewBox="0 0 18 18" width={size} height={size} aria-hidden="true">
    <circle cx="9" cy="9" r={radius} className="hud-gauge-track" />
    <circle cx="9" cy="9" r={radius} className="hud-gauge-fill" style={{strokeDasharray: `${(sweep / 360) * circumference} ${circumference}`}} />
  </svg>
}

function Chip({chip, onSelect, latency, tokens}) {
  const tone = chip.posture.hazard ? 'hazard' : chip.status === 'error' ? 'error' : chip.posture.writes ? 'writes' : 'read'
  return <button
    type="button"
    className={`hud-tag tone-${tone} status-${chip.status}${chip.selected ? ' selected' : ''}`}
    style={{transform: `translateX(${chip.x}px)`, width: chip.width, '--i': chip.index}}
    data-sequence={chip.sequence}
    onClick={() => onSelect(chip.selected ? null : chip.sequence)}
    aria-pressed={chip.selected}
    aria-label={`Exchange ${chip.ordinal}, ${chip.label}, ${chip.status}`}
    title={chip.operation}
  >
    <i className="hud-corner tl" /><i className="hud-corner tr" /><i className="hud-corner bl" /><i className="hud-corner br" />
    <span className="hud-tag-line">
      <b>{String(chip.ordinal).padStart(2, '0')}</b>
      <span>{chip.tone.label}</span>
      {chip.posture.posture !== 'unknown' && <em>{chip.posture.hazard ? 'DESTRUCTIVE' : chip.posture.posture.toUpperCase()}</em>}
    </span>
    <strong className="hud-tag-label">{chip.label}</strong>
    <span className="hud-tag-line meta">
      <Gauge sweep={chip.latencySweep} size={14} />
      <span>{latency}</span>
      <i className="hud-bar" aria-hidden="true"><b style={{width: `${Math.max(8, chip.tokenShare * 100)}%`}} /></i>
      <span>{tokens}</span>
      <i className={`hud-lamp status-${chip.status}`} aria-hidden="true" />
    </span>
    <i className="hud-scan" aria-hidden="true" />
  </button>
}

function Reticle({anchorsRef, sequence, active}) {
  const node = useRef(null)
  useEffect(() => {
    let frame = 0
    const paint = () => {
      frame = requestAnimationFrame(paint)
      const host = node.current
      if (!host) return
      const anchor = sequence === null ? null : anchorsRef.current?.[sequence]
      if (!anchor || !anchor.visible) {
        host.style.opacity = '0'
        return
      }
      host.style.opacity = '1'
      host.style.transform = `translate(${anchor.x}px, ${anchor.y}px)`
      host.classList.toggle('edge', Boolean(anchor.clamped))
    }
    frame = requestAnimationFrame(paint)
    return () => cancelAnimationFrame(frame)
  }, [anchorsRef, sequence])
  return <div ref={node} className={`hud-reticle${active ? ' locked' : ''}`} aria-hidden="true">
    <svg viewBox="-40 -40 80 80" width="80" height="80">
      <circle r="30" className="hud-reticle-ring outer" />
      <circle r="22" className="hud-reticle-ring inner" />
      <path d="M-34 0h10M24 0h10M0 -34v10M0 24v10" className="hud-reticle-ticks" />
      <circle r="2.2" className="hud-reticle-dot" />
    </svg>
    <span>{active ? 'LOCK' : 'TRACK'}</span>
    <em>▾</em>
  </div>
}

function Frame({headingRef, total, selected}) {
  const tape = useRef(null)
  useEffect(() => {
    let frame = 0
    const paint = () => {
      frame = requestAnimationFrame(paint)
      const node = tape.current
      if (!node) return
      node.style.transform = `translateX(${-(headingRef?.current || 0) * 1.6}px)`
    }
    frame = requestAnimationFrame(paint)
    return () => cancelAnimationFrame(frame)
  }, [headingRef])
  return <div className="hud-frame" aria-hidden="true">
    <svg className="hud-frame-arcs" viewBox="0 0 1000 600" preserveAspectRatio="none">
      <path d="M40 130 Q 500 30 960 130" className="hud-arc" />
      <path d="M60 138 Q 500 44 940 138" className="hud-arc faint" />
      <path d="M0 470 Q 500 560 1000 470" className="hud-arc faint" />
    </svg>
    <div className="hud-heading">
      <div className="hud-heading-window">
        <div className="hud-heading-tape" ref={tape}>
          {Array.from({length: 61}, (_, index) => {
            const value = (index - 30) * 5
            return <span key={index} className={value % 30 === 0 ? 'major' : ''}>{value % 30 === 0 ? <b>{Math.abs(value)}</b> : null}</span>
          })}
        </div>
        <i className="hud-heading-needle" />
      </div>
      <small>HEADING · {total} EXCHANGE{total === 1 ? '' : 'S'}{selected ? ' · LOCKED' : ''}</small>
    </div>
    <i className="hud-bracket tl" /><i className="hud-bracket tr" /><i className="hud-bracket bl" /><i className="hud-bracket br" />
  </div>
}

function Tethers({chips, anchorsRef, dockRef}) {
  const svg = useRef(null)
  useEffect(() => {
    let frame = 0
    const paint = () => {
      frame = requestAnimationFrame(paint)
      const host = svg.current
      const dock = dockRef.current
      if (!host || !dock) return
      const dockRect = dock.getBoundingClientRect()
      const hostRect = host.getBoundingClientRect()
      for (const line of host.querySelectorAll('line')) {
        const sequence = Number(line.dataset.sequence)
        const anchor = anchorsRef.current?.[sequence]
        const chipNode = dock.querySelector(`[data-sequence="${sequence}"]`)
        if (!anchor || !anchor.visible || !chipNode) {
          line.style.opacity = '0'
          continue
        }
        const chipRect = chipNode.getBoundingClientRect()
        const x1 = chipRect.left + chipRect.width / 2 - hostRect.left
        const y1 = chipRect.bottom - hostRect.top
        const x2 = anchor.x - hostRect.left
        const y2 = anchor.y - hostRect.top
        line.setAttribute('x1', String(x1))
        line.setAttribute('y1', String(y1))
        line.setAttribute('x2', String(x2))
        line.setAttribute('y2', String(y2))
        line.style.opacity = y2 > dockRect.bottom - hostRect.top ? '1' : '0'
      }
    }
    frame = requestAnimationFrame(paint)
    return () => cancelAnimationFrame(frame)
  }, [anchorsRef, dockRef, chips])
  return <svg ref={svg} className="hud-tethers" aria-hidden="true">
    {chips.map((chip) => <line key={chip.sequence} data-sequence={chip.sequence} className={chip.selected ? 'selected' : ''} />)}
  </svg>
}

function Tree({title, value, tone}) {
  const tree = useMemo(() => buildExchangeTree(value), [value])
  const [open, setOpen] = useState(() => initialOpenIds(tree.rows))
  useEffect(() => { setOpen(initialOpenIds(tree.rows)) }, [tree])
  const rows = useMemo(() => visibleRows(tree.rows, open), [tree, open])
  const toggle = (id) => setOpen((current) => {
    const next = new Set(current)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
  const copy = () => {
    try { navigator.clipboard?.writeText(JSON.stringify(value ?? null, null, 2)) } catch {}
  }
  return <section className="hud-tree">
    <div className="hud-tree-head">
      <strong>{title}</strong>
      <span>{formatByteSize(tree.bytes)}{tree.redactedCount ? ` · ${tree.redactedCount} REDACTED` : ''}</span>
      <button type="button" onClick={copy} title={`Copy ${title.toLowerCase()} JSON`}>COPY</button>
    </div>
    <ol>
      {rows.map((row) => <li
        key={row.id}
        className={`kind-${row.kind}${row.redacted ? ' redacted' : ''}${row.container ? ' container' : ''}`}
        style={{'--depth': row.depth}}
      >
        {row.container
          ? <button type="button" onClick={() => toggle(row.id)} aria-expanded={open.has(row.id)}>
              <i>{open.has(row.id) ? '▾' : '▸'}</i>
              {row.key && <b>{row.key}</b>}
              <span>{row.kind === 'array' ? `[${row.count}]` : `{${row.count}}`}</span>
              <small>{formatByteSize(row.bytes)}</small>
            </button>
          : <div>
              {row.key && <b>{row.key}</b>}
              <span className="hud-value">{row.redacted ? <u>{row.preview}</u> : row.preview}</span>
            </div>}
      </li>)}
    </ol>
  </section>
}

function Pane({record, chip, chapter, exchange, onClose}) {
  const flowMs = exchangeFlowMs(record.duration_ms)
  const [flowKey, setFlowKey] = useState(0)
  useEffect(() => { setFlowKey((value) => value + 1) }, [exchange?.schema, record.sequence])
  const posture = chip.posture
  const tone = posture.hazard ? 'hazard' : chip.status === 'error' ? 'error' : posture.writes ? 'writes' : 'read'
  const inputTokens = Number(record.input_tokens) || 0
  const outputTokens = Number(record.output_tokens) || 0
  const tokenTotal = Math.max(1, inputTokens + outputTokens)
  return <section
    className={`hud-pane tone-${tone} status-${chip.status}`}
    style={{'--flow-ms': `${flowMs}ms`}}
    role="dialog"
    aria-label={`Exchange ${chip.ordinal}: ${chip.label}`}
  >
    <i className="hud-corner tl" /><i className="hud-corner tr" /><i className="hud-corner bl" /><i className="hud-corner br" />
    <i className="hud-scan pane" aria-hidden="true" />
    <div className="hud-pane-head">
      <div className="hud-pane-identity">
        <span className="hud-pane-ordinal">@{String(record.sequence).padStart(2, '0')}</span>
        <div>
          <strong>{chip.label}</strong>
          <small>{record.operation}{chapter ? ` · ${chapter.title}` : ''}</small>
        </div>
      </div>
      <div className="hud-pane-flags">
        <span className="family">{chip.tone.label}</span>
        {record.modality && <span>{String(record.modality).toUpperCase()}</span>}
        {posture.posture !== 'unknown' && <span className="posture">{posture.hazard ? 'DESTRUCTIVE' : posture.posture.toUpperCase()}</span>}
        <span className={`state status-${chip.status}`}>{String(record.status || 'unknown').toUpperCase()}</span>
      </div>
      <button type="button" className="hud-pane-close" onClick={onClose} aria-label="Close the exchange">ESC</button>
    </div>
    <div className="hud-pane-gauges">
      <div className="hud-gauge-block">
        <Gauge sweep={chip.latencySweep} size={44} className="large" />
        <div><b>{formatNumber(record.duration_ms)}</b><small>MS LATENCY</small></div>
      </div>
      <div className="hud-gauge-block bars">
        <div className="hud-segments" aria-hidden="true">
          <i style={{width: `${(inputTokens / tokenTotal) * 100}%`}} className="in" />
          <i style={{width: `${(outputTokens / tokenTotal) * 100}%`}} className="out" />
        </div>
        <div><b>{formatNumber(inputTokens)}</b><small>IN</small><b>{formatNumber(outputTokens)}</b><small>OUT</small><b>{formatNumber(record.tokens_saved)}</b><small>AVOIDED</small></div>
      </div>
      <div className="hud-gauge-block text">
        <div><b>{Number.isFinite(record.estimated_cost_usd) ? `$${record.estimated_cost_usd.toFixed(6)}` : '—'}</b><small>COST</small></div>
        <div><b>{record.effect_profile?.scopes?.join(' · ') || 'not declared'}</b><small>SCOPE</small></div>
        {record.capability && <div><b>{record.capability.family} · {record.capability.interface || record.capability.label}</b><small>SYSTEM</small></div>}
      </div>
    </div>
    <div className="hud-flow" aria-hidden="true">
      <span>REQ</span>
      <i className="hud-flow-line"><b key={flowKey} className="hud-flow-packet" /></i>
      <span>RES</span>
      <small>{exchange?.truncated ? 'TRUNCATED · ' : ''}REDACTED COPY</small>
    </div>
    <div className="hud-exchange">
      {exchange?.loading && <p className="hud-exchange-note">RETRIEVING OWNER-PRIVATE EVIDENCE…</p>}
      {exchange?.error && <p className="hud-exchange-note error">{exchange.error}</p>}
      {exchange?.schema && <>
        <Tree title="REQUEST" value={exchange.request} tone={chip.tone} />
        <Tree title="RESPONSE" value={exchange.response} tone={chip.tone} />
      </>}
    </div>
  </section>
}

export default function Visor({chapter, records = [], selected, onSelect, exchange, anchorsRef, headingRef, playing}) {
  const viewportWidth = useViewportWidth()
  const dockRef = useRef(null)
  const selectedSequence = selected?.siteId === chapter?.id ? selected?.sequence ?? null : null
  const layout = useMemo(() => visorChips(records, {viewportWidth, selectedSequence}), [records, selectedSequence, viewportWidth])
  const select = (sequence) => onSelect(sequence === null ? null : {siteId: chapter.id, sequence})
  const record = records.find((item) => item.sequence === selectedSequence) || null
  const chip = layout.chips.find((item) => item.sequence === selectedSequence) || null
  const ordered = useMemo(() => [...records].sort((a, b) => Number(a.sequence) - Number(b.sequence)), [records])
  const reticleSequence = selectedSequence ?? ordered[0]?.sequence ?? null

  useEffect(() => {
    const onKey = (event) => {
      const target = event.target
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return
      if (!records.length) return
      if (event.key === 'Escape' && selectedSequence !== null) {
        event.preventDefault()
        select(null)
        return
      }
      if (event.key === 'ArrowRight' && selectedSequence !== null) {
        event.preventDefault()
        select(stepSequence(records, selectedSequence, 1))
        return
      }
      if (event.key === 'ArrowLeft' && selectedSequence !== null) {
        event.preventDefault()
        select(stepSequence(records, selectedSequence, -1))
        return
      }
      if (/^[1-9]$/.test(event.key) && !event.metaKey && !event.ctrlKey && !event.altKey) {
        const pick = ordered[Number(event.key) - 1]
        if (pick) {
          event.preventDefault()
          select(pick.sequence === selectedSequence ? null : pick.sequence)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [records, ordered, selectedSequence, chapter?.id])

  if (!chapter) return null
  return <div className={`hud${playing ? ' moving' : ''}${record ? ' unfolded' : ''}`} aria-label="Heads-up display">
    <Frame headingRef={headingRef} total={layout.total} selected={Boolean(record)} />
    <Tethers chips={layout.chips} anchorsRef={anchorsRef} dockRef={dockRef} />
    <Reticle anchorsRef={anchorsRef} sequence={reticleSequence} active={Boolean(record)} />
    <div className="hud-dock" ref={dockRef} key={chapter.id}>
      {layout.hiddenBefore > 0 && <span className="hud-overflow before">+{layout.hiddenBefore}</span>}
      {layout.chips.map((item) => {
        const source = records.find((entry) => entry.sequence === item.sequence)
        return <Chip key={item.sequence} chip={item} latency={`${formatNumber(source?.duration_ms || 0)} ms`} tokens={`${formatNumber(source?.tokens || 0)} tok`} onSelect={select} />
      })}
      {layout.hiddenAfter > 0 && <span className="hud-overflow after">+{layout.hiddenAfter}</span>}
      {!records.length && <span className="hud-empty">NO EXCHANGES AT THIS SITE</span>}
    </div>
    {record && chip && <Pane record={record} chip={chip} chapter={chapter} exchange={exchange} onClose={() => select(null)} />}
  </div>
}
