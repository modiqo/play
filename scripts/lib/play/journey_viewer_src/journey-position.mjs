function clamp(value) {
  return Math.max(0, Math.min(1, Number(value) || 0))
}

function denominator(story) {
  return Math.max(1, (story?.chapters?.length || 1) - 1)
}

/**
 * Reconcile viewport position when a graph is first opened or gains a call site.
 * Every workspace opens at the beginning. Only an explicit live-head mode advances;
 * an inspected or frozen call site keeps its identity.
 */
export function reconcileJourneyPosition({
  previousStory,
  nextStory,
  replay = 0,
  selected = null,
  quiet = false,
  followHead = false,
} = {}) {
  if (!quiet) return 0
  const nextChapters = nextStory?.chapters || []
  if (!nextChapters.length) return 0
  if (followHead && nextStory?.state === 'active' && !selected?.siteId) return 1

  if (selected?.siteId) {
    const selectedIndex = nextChapters.findIndex((chapter) => chapter.id === selected.siteId)
    if (selectedIndex >= 0) return selectedIndex / denominator(nextStory)
  }

  const previousChapters = previousStory?.chapters || []
  if (!previousChapters.length) return clamp(replay)
  const previousUnits = clamp(replay) * denominator(previousStory)
  const previousIndex = Math.min(previousChapters.length - 1, Math.floor(previousUnits + .001))
  const previousChapter = previousChapters[previousIndex]
  const nextIndex = nextChapters.findIndex((chapter) => chapter.id === previousChapter?.id)
  if (nextIndex < 0) return clamp(previousUnits / denominator(nextStory))
  const localProgress = Math.max(0, Math.min(.999, previousUnits - previousIndex))
  return clamp((nextIndex + localProgress) / denominator(nextStory))
}

/**
 * Keep dense worlds bounded around the current vantage. Small journeys retain
 * their complete history; long journeys retain nearby context and one preview.
 */
export function journeyVisibilityWindow(siteCount, reached, {
  denseThreshold = 18,
  history = 4,
  preview = 1,
} = {}) {
  const count = Math.max(0, Number(siteCount) || 0)
  const current = Math.max(0, Math.min(Math.max(0, count - 1), Number(reached) || 0))
  return {
    start: count > denseThreshold ? Math.max(0, current - history) : 0,
    end: Math.min(Math.max(0, count - 1), current + preview),
  }
}

const TRACKER_LANDMARK_KINDS = new Set([
  'intent', 'decision', 'capability', 'authority', 'blocker', 'recovery',
  'evidence', 'milestone', 'artifact', 'play_candidate', 'play',
])

function trackerImportance(chapters, index) {
  const kind = chapters[index]?.kind || ''
  const previousKind = chapters[index - 1]?.kind || ''
  const nextKind = chapters[index + 1]?.kind || ''
  return (TRACKER_LANDMARK_KINDS.has(kind) ? 8 : 0)
    + (kind !== previousKind ? 3 : 0)
    + (kind !== nextKind ? 1 : 0)
}

/**
 * Project a long journey onto a small number of semantic landmarks. The rail
 * remains globally proportional; each time region contributes its most
 * meaningful world-model transition instead of another indistinguishable dot.
 */
export function journeyTrackerIndexes(chaptersOrCount, currentIndex, maxMarkers = 14) {
  const chapters = Array.isArray(chaptersOrCount)
    ? chaptersOrCount
    : Array.from({length: Math.max(0, Math.floor(Number(chaptersOrCount) || 0))}, () => ({}))
  const count = chapters.length
  if (!count) return []
  const current = Math.max(0, Math.min(count - 1, Math.floor(Number(currentIndex) || 0)))
  const limit = Math.max(3, Math.floor(Number(maxMarkers) || 14))
  if (count <= limit) return Array.from({length: count}, (_, index) => index)

  const selected = new Set([0, count - 1, current])
  const availableSlots = limit - selected.size
  const interiorCount = Math.max(0, count - 2)
  for (let slot = 0; slot < availableSlots; slot += 1) {
    const start = 1 + Math.floor(slot / availableSlots * interiorCount)
    const end = Math.min(count - 2, Math.floor((slot + 1) / availableSlots * interiorCount))
    const center = (start + end) / 2
    let best = -1
    for (let index = start; index <= end; index += 1) {
      if (selected.has(index)) continue
      if (best < 0
        || trackerImportance(chapters, index) > trackerImportance(chapters, best)
        || (trackerImportance(chapters, index) === trackerImportance(chapters, best)
          && Math.abs(index - center) < Math.abs(best - center))) {
        best = index
      }
    }
    if (best >= 0) selected.add(best)
  }
  return [...selected].sort((left, right) => left - right)
}
