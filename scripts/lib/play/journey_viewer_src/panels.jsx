import React from 'react'
import {formatNumber} from './format.js'
import {KIND_LABEL, MAP_MEANING, WORLD_ROLE, WORLD_STORY} from './semantics.js'

export function Telemetry({story, open, onToggle}) {
  const latency = Number(story?.telemetry.duration_ms || 0)
  const tokens = Number(story?.telemetry.payload_tokens || 0)
  const avoided = Number(story?.telemetry.tokens_saved || 0)
  const denominator = Math.max(1, tokens + avoided)
  return <section className={`telemetry${open ? ' open' : ''}`}>
    <button className="telemetry-toggle" onClick={onToggle} aria-expanded={open}><span>TELEMETRY</span><strong>{formatNumber(latency)} ms · {formatNumber(tokens)} tok</strong><i>{open ? '×' : '+'}</i></button>
    <div className="telemetry-body">
      <div className="metric"><span>LATENCY</span><strong>{formatNumber(latency)}<small> ms</small></strong><i style={{'--fill': `${Math.min(100, Math.log10(latency + 1) * 24)}%`}} /></div>
      <div className="metric"><span>CONSUMED</span><strong>{formatNumber(tokens)}</strong><i style={{'--fill': `${tokens / denominator * 100}%`}} /></div>
      <div className="metric saved"><span>AVOIDED</span><strong>{formatNumber(avoided)}</strong><i style={{'--fill': `${avoided / denominator * 100}%`}} /></div>
    </div>
  </section>
}

const WHY = {
  intent: 'Establish the requested outcome before choosing tools or taking effects.',
  decision: 'Choose the next route while preserving the user’s constraints and authority.',
  capability: 'Prepare the capability needed to advance the outcome.',
  authority: 'Confirm that the next effect is allowed before it occurs.',
  phase: 'Group related commands into one understandable stage of the outcome.',
  effect: 'Perform outcome-bearing work through the selected capability.',
  evidence: 'Check the observed result before treating the work as complete.',
  blocker: 'Expose what prevented progress instead of hiding it behind retries.',
  recovery: 'Re-enter the useful path with verified corrective evidence.',
  milestone: 'Record a meaningful boundary in the completed journey.',
  artifact: 'Turn the verified work into something the user can use.',
  play_candidate: 'Compress the successful trajectory into a reusable procedure.',
  play: 'Make the verified procedure available for future runs.',
}

export function JourneyGuide({story, interactions, replay, playing, frozen, onOpen, onNavigate}) {
  if (!story?.chapters?.length) return null
  const playbackIndex = Math.max(0, Math.min(story.chapters.length - 1, Math.ceil(replay * story.chapters.length) - 1))
  const liveIndex = Math.max(0, story.chapters.findIndex((chapter) => chapter.id === story.current_chapter))
  const restingIndex = story.state === 'active' ? liveIndex : story.chapters.length - 1
  const index = playing || replay < .999 ? playbackIndex : restingIndex
  const current = story.chapters[index]
  const next = story.chapters[index + 1]
  const records = interactions?.sites?.[current.id] || []
  const capabilities = [...new Set(records.map(capabilityName))]
  const effects = [...new Set(records.map((record) => record.effect).filter(Boolean))]
  const latency = records.reduce((sum, record) => sum + Number(record.duration_ms || 0), 0)
  const consumed = records.reduce((sum, record) => sum + Number(record.tokens || 0), 0)
  const succeeded = records.filter((record) => record.status === 'succeeded').length
  return <aside className={`journey-guide${frozen ? ' frozen' : ''}`} onClick={() => onOpen({siteId: current.id, sequence: null})}>
    <div className="guide-kicker"><i />{playing ? 'TRAVERSING' : frozen ? 'FROZEN VANTAGE' : story.state === 'active' ? 'NOW' : 'RECORDED JOURNEY'}<span>{String(index + 1).padStart(2, '0')} / {String(story.chapters.length).padStart(2, '0')}</span></div>
    <h1>{current.title}</h1>
    <p><strong>{KIND_LABEL[current.kind] || current.kind} → {WORLD_ROLE[current.kind] || 'journey stage'}.</strong> {WORLD_STORY[current.kind] || WHY[current.kind] || 'Advance the requested outcome while preserving evidence.'}</p>
    {frozen && <div className="vantage-nudge"><strong>EXPLORE</strong><span>Drag or use arrow keys to look through 360°. Scroll to move forward or backward. Every illuminated callout opens that structure’s evidence.</span></div>}
    <dl>
      <dt>HAPPENED</dt><dd>{current.detail || current.title}</dd>
      <dt>STRUCTURES</dt><dd>{records.length ? `${records.length} illuminated · select any callout for evidence` : 'No tool interactions recorded at this vantage'}</dd>
      <dt>CAPABILITIES</dt><dd>{capabilities.length ? capabilities.join(' · ') : 'No tool capability used here'}</dd>
      <dt>EFFECT</dt><dd>{effects.length ? effects.join(' · ') : current.kind === 'effect' ? 'Outcome-bearing work' : 'No external effect recorded'}</dd>
      <dt>INSIGHT</dt><dd>{succeeded}/{records.length} interactions succeeded · {formatNumber(consumed)} tokens · {formatNumber(latency)} ms</dd>
      <dt>NEXT</dt><dd>{next?.title || 'Deliver the verified outcome'}</dd>
    </dl>
    {frozen && <nav className="vantage-navigation" aria-label="Frozen vantage navigation">
      <button disabled={index === 0} onClick={(event) => { event.stopPropagation(); onNavigate(index - 1) }}>← PRIOR VANTAGE</button>
      <span>ROUTE DIRECTION</span>
      <button className="forward" disabled={index >= story.chapters.length - 1} onClick={(event) => { event.stopPropagation(); onNavigate(index + 1) }}>FORWARD →</button>
    </nav>}
    <div className="guide-progress"><i style={{width: `${Math.max(2, (index + 1) / story.chapters.length * 100)}%`}} /></div>
  </aside>
}

const WORLD_MODEL_KINDS = ['intent', 'capability', 'authority', 'effect', 'evidence', 'blocker', 'recovery', 'milestone', 'artifact', 'play_candidate']

export function WorldModel({open, onToggle}) {
  return <>
    <button className="world-model-toggle" onClick={onToggle} aria-expanded={open}>◇ WORLD MODEL</button>
    <aside className={`world-model${open ? ' open' : ''}`}>
      <div className="panel-heading"><span>HOW TO READ THIS WORLD</span><button onClick={onToggle}>×</button></div>
      <p>The same spatial vocabulary repeats across every journey. Shape tells you what role a place has before you inspect its evidence.</p>
      <dl>{WORLD_MODEL_KINDS.map((kind) => <React.Fragment key={kind}>
        <dt><i className={`world-glyph ${kind}`} />{KIND_LABEL[kind]}</dt>
        <dd><strong>{WORLD_ROLE[kind]}</strong><span>{WORLD_STORY[kind]}</span></dd>
      </React.Fragment>)}</dl>
      <div className="world-model-note"><i className="route-mark" />The amber route is the agent’s path. Structures around a stop are recorded interactions; select one to inspect its redacted exchange.</div>
    </aside>
  </>
}

function capabilityName(record) {
  if (record.provider) return record.provider
  const operation = String(record.operation || 'local')
  return operation.split(/[\s.]/)[0] || 'local'
}

export function CapabilityRail({story, interactions, replay, onJump}) {
  const chapterIndex = Math.max(0, Math.min(story.chapters.length - 1, Math.floor(replay * Math.max(1, story.chapters.length - 1) + .001)))
  const currentChapter = story.chapters[chapterIndex]
  const activeNames = new Set((interactions?.sites?.[currentChapter?.id] || []).map(capabilityName))
  const entries = []
  const byName = new Map()
  story.chapters.forEach((chapter) => {
    for (const record of interactions?.sites?.[chapter.id] || []) {
      const name = capabilityName(record)
      const existing = byName.get(name)
      const entry = existing || {name, first: chapter.order, last: chapter.order, count: 0}
      entry.first = Math.min(entry.first, chapter.order)
      entry.last = Math.max(entry.last, chapter.order)
      entry.count += 1
      byName.set(name, entry)
    }
  })
  for (const entry of byName.values()) entries.push(entry)
  entries.sort((left, right) => {
    const leftActive = activeNames.has(left.name) ? 0 : 1
    const rightActive = activeNames.has(right.name) ? 0 : 1
    return leftActive - rightActive || left.first - right.first || left.name.localeCompare(right.name)
  })
  if (!entries.length) return null
  return <aside className="capability-rail">
    <h2>CAPABILITIES</h2><p>What the agent can use on this journey</p>
    <div>{entries.slice(0, 8).map((entry) => {
      const active = activeNames.has(entry.name)
      const used = entry.first <= chapterIndex
      return <button key={entry.name} className={active ? 'active' : used ? 'used' : ''} onClick={() => onJump(entry.first)}>
        <i /><span>{entry.name}</span><small>{active ? 'IN USE' : used ? 'USED' : 'AVAILABLE'}</small><em>{entry.count}</em>
      </button>
    })}</div>
  </aside>
}


