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

  it('matches the reference default and varies density inside an ellipse without an outer rectangle', () => {
    const first = { x: 0, y: 0 }, last = { x: 100, y: 200 }
    const standard = faceGridPolylines(first, last)
    expect(standard).toHaveLength(30)
    expect(standard.filter(line => line.length === 2)).toHaveLength(15)
    expect(standard.filter(line => line.length > 2)).toHaveLength(15)
    expect(faceGridPolylines(first, last, 8)).toHaveLength(14)
    expect(faceGridPolylines(first, last, 24)).toHaveLength(46)
    expect(standard.flat().every(point => ((point.x - 50) / 50) ** 2 + ((point.y - 100) / 100) ** 2 <= 1.000001)).toBe(true)
  })
})
