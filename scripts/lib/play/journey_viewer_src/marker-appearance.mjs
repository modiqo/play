/** Update the renderer-owned appearance of an interaction marker defensively. */
export function updateMarkerAppearance(marker, {
  selected = false,
  proximity = false,
  pulse = 0,
  frozen = false,
  future = false,
  muted = false,
} = {}) {
  const subdued = future || muted
  const beadMaterial = marker?.bead?.material
  if (beadMaterial) {
    beadMaterial.emissiveIntensity = selected ? .12 : subdued ? .002 : proximity ? .018 + pulse * .035 : .008
    beadMaterial.opacity = selected ? .72 : subdued ? (future ? .035 : .05) : proximity ? .46 : .3
  }
  const haloMaterial = marker?.halo?.material
  if (haloMaterial) haloMaterial.opacity = selected ? 1 : subdued ? (future ? .008 : .015) : proximity ? .24 + pulse * .34 : .07
  const scale = selected ? 1.16 : proximity && !frozen && !subdued ? 1 + Math.max(0, pulse) * .035 : 1
  marker?.bead?.scale?.setScalar?.(scale)
  marker?.halo?.scale?.setScalar?.(selected ? 1.08 : 1)
  marker?.indexRoot?.classList?.toggle?.('selected', selected)
  marker?.indexRoot?.classList?.toggle?.('muted', muted)
  marker?.indexRoot?.classList?.toggle?.('future', future)
}

/** The bead is the resting evidence control; its expanded plaque appears only after selection. */
export function plaqueIsVisible({selected = false} = {}) {
  return Boolean(selected)
}
