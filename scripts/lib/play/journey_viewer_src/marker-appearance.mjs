/** Update the renderer-owned appearance of an interaction marker defensively. */
export function updateMarkerAppearance(marker, {
  selected = false,
  proximity = false,
  pulse = 0,
  frozen = false,
  future = false,
  muted = false,
  temporalRelation = null,
} = {}) {
  const previous = temporalRelation === 'previous'
  const next = temporalRelation === 'next'
  const adjacent = previous || next
  const subdued = future || muted
  const beadMaterial = marker?.bead?.material
  if (beadMaterial) {
    beadMaterial.emissive?.setHex?.(selected ? 0xf1f4f3 : next ? 0xe88413 : previous ? 0xaeb8ba : 0x8e999d)
    beadMaterial.emissiveIntensity = selected ? .12 : subdued ? .002 : next ? .065 : previous ? .038 : proximity ? .018 + pulse * .035 : .008
    beadMaterial.opacity = selected ? .72 : subdued ? (future ? .035 : .05) : next ? .38 : previous ? .3 : proximity ? .46 : .3
  }
  const haloMaterial = marker?.halo?.material
  if (haloMaterial) haloMaterial.opacity = selected ? 1 : subdued ? (future ? .008 : .015) : next ? .18 : previous ? .12 : proximity ? .24 + pulse * .34 : .07
  const scale = selected ? 1.16 : adjacent && !subdued ? (next ? 1.055 : 1.035) : proximity && !frozen && !subdued ? 1 + Math.max(0, pulse) * .035 : 1
  marker?.bead?.scale?.setScalar?.(scale)
  marker?.halo?.scale?.setScalar?.(selected ? 1.08 : 1)
  marker?.indexRoot?.classList?.toggle?.('selected', selected)
  marker?.indexRoot?.classList?.toggle?.('muted', muted)
  marker?.indexRoot?.classList?.toggle?.('future', future)
  marker?.indexRoot?.classList?.toggle?.('temporal-previous', previous)
  marker?.indexRoot?.classList?.toggle?.('temporal-next', next)
}

/** Resolve immediate chronological context without using screen-space proximity. */
export function temporalNeighborhood(markers = [], selectedSequence = null) {
  const selectedIndex = selectedSequence === null || selectedSequence === undefined
    ? -1
    : markers.findIndex((marker) => marker?.sequence === selectedSequence)
  const markerRelations = markers.map((_marker, index) => {
    if (index === selectedIndex) return 'current'
    if (index === selectedIndex - 1) return 'previous'
    if (index === selectedIndex + 1) return 'next'
    return null
  })
  const segmentRelations = markers.slice(1).map((_marker, index) => {
    if (index === selectedIndex - 1) return 'previous'
    if (index === selectedIndex) return 'next'
    return null
  })
  return {selectedIndex, markerRelations, segmentRelations}
}

/** The bead is the resting evidence control; its expanded plaque appears only after selection. */
export function plaqueIsVisible({selected = false} = {}) {
  return Boolean(selected)
}
