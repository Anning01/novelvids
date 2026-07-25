import type { ImageAnnotation, Point } from '../types/workbenchTypes'

export type AnnotationEditorTool = 'move' | ImageAnnotation['tool']

export interface ImageBounds {
  left: number
  top: number
  width: number
  height: number
}

export interface AnnotationState {
  shapes: ImageAnnotation[]
  history: ImageAnnotation[][]
}

export type AnnotationAction =
  | { type: 'load'; shapes: ImageAnnotation[] }
  | { type: 'add'; shape: ImageAnnotation }
  | { type: 'clear' }
  | { type: 'undo' }

const cloneShapes = (shapes: ImageAnnotation[]) => shapes.map(shape => ({
  ...shape,
  points: shape.points.map(point => ({ ...point })),
}))
const clampUnit = (value: number) => Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0))

export function normalizeImagePoint(clientPoint: Point, imageBounds: ImageBounds): Point {
  if (imageBounds.width <= 0 || imageBounds.height <= 0) return { x: 0, y: 0 }
  return {
    x: clampUnit((clientPoint.x - imageBounds.left) / imageBounds.width),
    y: clampUnit((clientPoint.y - imageBounds.top) / imageBounds.height),
  }
}

export function emptyAnnotationState(): AnnotationState {
  return { shapes: [], history: [] }
}

export function annotationReducer(state: AnnotationState, action: AnnotationAction): AnnotationState {
  if (action.type === 'load') return { shapes: cloneShapes(action.shapes), history: [] }
  if (action.type === 'undo') {
    const previous = state.history.at(-1)
    return previous ? { shapes: cloneShapes(previous), history: state.history.slice(0, -1) } : state
  }
  if (action.type === 'clear') {
    if (!state.shapes.length) return state
    return { shapes: [], history: [...state.history, cloneShapes(state.shapes)] }
  }
  return {
    shapes: [...state.shapes, { ...action.shape, points: action.shape.points.map(point => ({ ...point })) }],
    history: [...state.history, cloneShapes(state.shapes)],
  }
}
