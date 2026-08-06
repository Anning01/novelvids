import { expect, it } from 'vitest'
import type { ImageAnnotation } from '../types/workbenchTypes'
import {
  annotationReducer,
  emptyAnnotationState,
  normalizeImagePoint,
} from './imageAnnotations'

const rect: ImageAnnotation = {
  id: 'rect-1',
  tool: 'rectangle',
  points: [{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 }],
  stroke: '#ff5a5f',
  strokeWidth: 3,
}
const arrow: ImageAnnotation = {
  id: 'arrow-1',
  tool: 'arrow',
  points: [{ x: 0.2, y: 0.2 }, { x: 0.8, y: 0.8 }],
  stroke: '#ff5a5f',
  strokeWidth: 3,
}

it('normalizes points within zero and one', () => {
  expect(normalizeImagePoint(
    { x: 150, y: 100 },
    { left: 100, top: 50, width: 200, height: 100 },
  )).toEqual({ x: 0.25, y: 0.5 })
  expect(normalizeImagePoint(
    { x: 50, y: 500 },
    { left: 100, top: 50, width: 200, height: 100 },
  )).toEqual({ x: 0, y: 1 })
})

it('undoes the last shape and clear is itself undoable', () => {
  const withOne = annotationReducer(emptyAnnotationState(), { type: 'add', shape: rect })
  const withTwo = annotationReducer(withOne, { type: 'add', shape: arrow })
  expect(annotationReducer(withTwo, { type: 'undo' }).shapes).toEqual([rect])
  const cleared = annotationReducer(withTwo, { type: 'clear' })
  expect(annotationReducer(cleared, { type: 'undo' }).shapes).toEqual([rect, arrow])
})

it('resets history when annotations are loaded', () => {
  const loaded = annotationReducer(emptyAnnotationState(), { type: 'load', shapes: [rect] })
  expect(loaded.shapes).toEqual([rect])
  expect(annotationReducer(loaded, { type: 'undo' }).shapes).toEqual([rect])
})
