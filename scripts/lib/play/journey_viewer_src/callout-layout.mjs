export function horizontalCalloutOffsets({edgeX = 0, width = 0, worldCallout = false, direction = -1} = {}) {
  if (!worldCallout) return [edgeX, edgeX + direction * 38, edgeX - direction * 38, edgeX + direction * 78]

  // The central proof card should yield to the persistent telemetry instrument.
  // Prefer modest rightward steps, then try the left only when the right rail
  // leaves no viable room.
  const step = Math.max(38, Math.round(width * .12))
  return [edgeX, edgeX + step, edgeX + step * 2, edgeX + step * 3, edgeX - step, edgeX - step * 2]
}
