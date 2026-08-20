function clamp(value) {
  return Math.max(0, Math.min(1, Number(value) || 0))
}

function denominator(story) {
  return Math.max(1, (story?.chapters?.length || 1) - 1)
}

/**
 * Reconcile viewport position when a live graph gains another call site.
 * The live head advances; an inspected/frozen call site keeps its identity.
 */
export function reconcileJourneyPosition({
  previousStory,
  nextStory,
  replay = 0,
  selected = null,
  quiet = false,
  followHead = false,
} = {}) {
  if (!quiet) return nextStory?.state === 'active' ? 1 : 0
  const nextChapters = nextStory?.chapters || []
  if (!nextChapters.length) return 0
  if (followHead && nextStory?.state === 'active' && replay >= .999 && !selected?.siteId) return 1

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
