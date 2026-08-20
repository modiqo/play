/** Update the renderer-owned appearance of an interaction marker defensively. */
export function updateMarkerAppearance(marker, {selected = false, proximity = false, pulse = 0, frozen = false} = {}) {
  const towerMaterial = marker?.tower?.material
  if (towerMaterial) {
    towerMaterial.emissiveIntensity = proximity ? .018 + pulse * .035 : .008
    towerMaterial.opacity = selected ? .56 : proximity ? .46 : .3
  }
  const edgeMaterial = marker?.edge?.material
  if (edgeMaterial) edgeMaterial.opacity = selected ? 1 : proximity ? .3 + pulse * .48 : .1
  if (marker?.tower?.scale) marker.tower.scale.y = proximity && !frozen ? 1 + Math.max(0, pulse) * .025 : 1
}

/** Plaques are evidence controls, so they reveal at rest rather than shimmer while the camera traverses. */
export function plaqueIsVisible({isCurrent = false, selected = false, playing = false, frozen = false} = {}) {
  return Boolean(selected || (isCurrent && (frozen || !playing)))
}
