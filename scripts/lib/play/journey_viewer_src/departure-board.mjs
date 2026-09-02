/**
 * Departure board: the opening scene where a journey is chosen.
 *
 * Pure grouping and labelling over the workspace index, so the board and the
 * arrival handoff can be tested without a renderer.
 */

import {journeyActivityEpoch, journeyActivityLabel, journeyKind, journeyPickerItems} from './journey-picker.mjs'

export const BOARD_SECTIONS = Object.freeze([
  {id: 'live', title: 'LIVE NOW', note: 'A harness is driving these right now'},
  {id: 'recorded', title: 'RECORDED', note: 'Completed journeys with evidence · newest first'},
  {id: 'workspace', title: 'WORKSPACES', note: 'Rote workspaces that can be projected on demand'},
  {id: 'tutorial', title: 'START HERE', note: 'A guided drive through the journey world'},
])

export function boardSectionFor(item = {}) {
  if (item.tutorial) return 'tutorial'
  if (item.journey_mode === 'live') return 'live'
  if (item.journey_mode === 'workspace') return 'workspace'
  return 'recorded'
}

export function boardAvailability(item = {}) {
  if (item.graph_ready) return {ready: true, label: 'DRIVE'}
  if (item.projectable) return {ready: true, label: 'BUILD MAP · DRIVE'}
  if (item.workspace_available) return {ready: false, label: 'NO PLAY JOURNEY'}
  return {ready: false, label: 'NO EVIDENCE'}
}

export function boardFacts(item = {}, nowMs = Date.now()) {
  const availability = boardAvailability(item)
  return {
    kind: journeyKind(item),
    activity: journeyActivityLabel(item, nowMs),
    sites: Number(item.nodes) || 0,
    routes: Number(item.edges) || 0,
    exchanges: Number(item.commands) || 0,
    live: item.journey_mode === 'live' && Boolean(item.active_recently),
    ...availability,
  }
}

/** Sections in board order, each with its items newest first; empty sections are dropped. */
export function boardSections(items = []) {
  const ordered = journeyPickerItems(items)
  return BOARD_SECTIONS
    .map((section) => ({...section, items: ordered.filter((item) => boardSectionFor(item) === section.id)}))
    .filter((section) => section.items.length > 0)
}

/** A short ladder of site markers so a card shows its scale without inventing a route. */
export function siteLadder(count, max = 14) {
  const total = Math.max(0, Math.floor(Number(count) || 0))
  const shown = Math.min(total, max)
  return {shown, overflow: Math.max(0, total - shown)}
}

/** The next journeys to offer at arrival: live first, then the newest, never the current one. */
export function nextJourneys(items = [], currentId = '', limit = 3) {
  const ordered = journeyPickerItems(items).filter((item) => item.id !== currentId && boardAvailability(item).ready)
  const live = ordered.filter((item) => item.journey_mode === 'live')
  const rest = ordered.filter((item) => item.journey_mode !== 'live' && !item.tutorial)
  const tutorial = ordered.filter((item) => item.tutorial)
  return [...live, ...rest, ...tutorial].slice(0, Math.max(0, limit))
}

/** Departure countdown seconds for a freshly chosen journey; live tracking never counts down. */
export function departureCountdown({live = false, tracking = false, seconds = 3} = {}) {
  if (live && tracking) return 0
  return Math.max(0, Math.floor(seconds))
}

export {journeyActivityEpoch}
