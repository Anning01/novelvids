import { describe, expect, it } from 'vitest'
import { faceGridPolylines } from './imageAnnotationGeometry'

describe('faceGridPolylines', () => {
  it('creates latitude and longitude lines inside the requested ellipse', () => {
    const lines = faceGridPolylines({ x: 10, y: 20 }, { x: 110, y: 220 }, 8, 12)
    expect(lines).toHaveLength(14)
    expect(lines.flat().every(point => point.x >= 10 && point.x <= 110)).toBe(true)
    expect(lines.flat().every(point => point.y >= 20 && point.y <= 220)).toBe(true)
  })

  it('does not create a grid for an empty selection', () => {
    expect(faceGridPolylines({ x: 1, y: 1 }, { x: 1, y: 1 })).toEqual([])
  })
})
