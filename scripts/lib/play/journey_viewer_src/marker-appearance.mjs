/** Update the renderer-owned appearance of an interaction marker defensively. */
export function updateMarkerAppearance(marker, {selected = false, proximity = false, pulse = 0, frozen = false} = {}) {
  const towerMaterial = marker?.tower?.material
  if (towerMaterial) {
    towerMaterial.emissiveIntensity = proximity ? .025 + pulse * .07 : .01
    towerMaterial.opacity = selected ? .52 : proximity ? .4 : .26
  }
  const edgeMaterial = marker?.edge?.material
  if (edgeMaterial) edgeMaterial.opacity = selected ? 1 : proximity ? .3 + pulse * .48 : .1
  if (marker?.tower?.scale) marker.tower.scale.y = proximity && !frozen ? 1 + Math.max(0, pulse) * .025 : 1
}
