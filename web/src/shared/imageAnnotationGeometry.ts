export interface AnnotationPoint {
  x: number
  y: number
}

export const FACE_GRID_DENSITY = { min: 4, max: 32, step: 2, default: 16 } as const

function sampleAngles(start: number, end: number, count: number) {
  return Array.from({ length: count + 1 }, (_, index) => start + ((end - start) * index) / count)
}

export function faceGridPolylines(
  first: AnnotationPoint,
  last: AnnotationPoint,
  divisions: number = FACE_GRID_DENSITY.default,
  curveSamples = 40,
): AnnotationPoint[][] {
  const left = Math.min(first.x, last.x)
  const right = Math.max(first.x, last.x)
  const top = Math.min(first.y, last.y)
  const bottom = Math.max(first.y, last.y)
  const centerX = (left + right) / 2
  const centerY = (top + bottom) / 2
  const radiusX = (right - left) / 2
  const radiusY = (bottom - top) / 2
  if (radiusX <= 0 || radiusY <= 0) return []

  const safeDivisions = Math.min(FACE_GRID_DENSITY.max, Math.max(2,
    Number.isFinite(divisions) ? Math.round(divisions) : FACE_GRID_DENSITY.default))
  const safeSamples = Math.max(8, Math.round(curveSamples))
  const latitudes = Array.from({ length: safeDivisions - 1 }, (_, index) => {
    const latitude = -Math.PI / 2 + (Math.PI * (index + 1)) / safeDivisions
    const y = centerY + radiusY * Math.sin(latitude)
    const halfWidth = radiusX * Math.cos(latitude)
    return [{ x: centerX - halfWidth, y }, { x: centerX + halfWidth, y }]
  })
  const latitudeSamples = sampleAngles(-Math.PI / 2, Math.PI / 2, safeSamples)
  const longitudes = Array.from({ length: safeDivisions - 1 }, (_, index) => {
    const longitude = -Math.PI / 2 + (Math.PI * (index + 1)) / safeDivisions
    return latitudeSamples.map(latitude => ({
      x: centerX + radiusX * Math.sin(longitude) * Math.cos(latitude),
      y: centerY + radiusY * Math.sin(latitude),
    }))
  })
  return [...latitudes, ...longitudes]
}
