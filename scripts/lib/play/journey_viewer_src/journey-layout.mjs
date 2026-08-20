/**
 * Canonical renderer-neutral coordinates for every journey vantage.
 *
 * Follow, Atlas, and Audit must all project the same terrain. Renderers may
 * choose different cameras and levels of detail, but may not invent another
 * route or reorder the sites.
 */
export function journeyCoordinates(chapters = []) {
  return chapters.map((_chapter, index) => ({
    x: Math.sin(index * .72) * 12 + Math.sin(index * .23) * 4,
    y: 0,
    z: index * -21,
  }))
}
