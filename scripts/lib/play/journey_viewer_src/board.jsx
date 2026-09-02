import React, {useEffect} from 'react'
import {boardFacts, boardSections, siteLadder} from './departure-board.mjs'

/**
 * The departure board: full-screen journey catalog shown before the cockpit
 * and whenever the driver asks to change destination.
 */

function Ladder({count}) {
  const ladder = siteLadder(count)
  return <span className="board-ladder" aria-hidden="true">
    {Array.from({length: ladder.shown}, (_, index) => <i key={index} />)}
    {ladder.overflow > 0 && <small>+{ladder.overflow}</small>}
  </span>
}

function Card({item, current, onChoose}) {
  const facts = boardFacts(item)
  return <button
    type="button"
    className={`board-card${current ? ' current' : ''}${facts.live ? ' live' : ''}${facts.ready ? '' : ' unavailable'}`}
    disabled={!facts.ready}
    onClick={() => onChoose(item)}
  >
    <i className="hud-corner tl" /><i className="hud-corner tr" /><i className="hud-corner bl" /><i className="hud-corner br" />
    <span className="board-card-head">
      <b className={`journey-kind kind-${facts.kind.toLowerCase().replaceAll(' ', '-')}`}>{facts.kind}</b>
      <time>{facts.activity}</time>
    </span>
    <strong>{item.intent}</strong>
    <Ladder count={facts.sites} />
    <span className="board-card-facts">
      <span><b>{facts.sites}</b> SITES</span>
      <span><b>{facts.routes}</b> ROUTES</span>
      <span><b>{facts.exchanges}</b> EXCHANGES</span>
    </span>
    <span className="board-card-go">{current ? 'CURRENT · DRIVE AGAIN' : facts.label}<em>›</em></span>
  </button>
}

export default function DepartureBoard({items = [], current = '', onChoose, onClose, canClose = false, refreshing = false, onRefresh}) {
  const sections = boardSections(items)
  useEffect(() => {
    if (!canClose) return undefined
    const onKey = (event) => { if (event.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [canClose, onClose])
  return <section className="board" role="dialog" aria-label="Choose a journey">
    <div className="board-frame">
      <header className="board-head">
        <div>
          <span>DEPARTURES</span>
          <h1>Choose a journey</h1>
          <p>Pick a route and the drive begins. NEWEST FIRST within each board.</p>
        </div>
        <div className="board-actions">
          <button type="button" onClick={onRefresh} disabled={refreshing} title="Refresh the catalog">{refreshing ? 'REFRESHING…' : 'REFRESH ↻'}</button>
          {canClose && <button type="button" onClick={onClose} title="Back to the drive">BACK TO DRIVE · ESC</button>}
        </div>
      </header>
      {sections.length === 0 && <p className="board-empty">No journeys yet. Run a Play or start an exploration, then refresh.</p>}
      {sections.map((section) => <div className={`board-section section-${section.id}`} key={section.id}>
        <div className="board-section-head"><strong>{section.title}</strong><span>{section.note}</span><b>{section.items.length}</b></div>
        <div className="board-grid">
          {section.items.map((item) => <Card key={item.id} item={item} current={item.id === current} onChoose={onChoose} />)}
        </div>
      </div>)}
    </div>
  </section>
}
