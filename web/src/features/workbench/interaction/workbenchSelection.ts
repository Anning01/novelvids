import type { NodeChange } from '@vue-flow/core'

export function applyNodeSelectionChanges(
  current: string[],
  changes: NodeChange[],
  validKeys: ReadonlySet<string>,
) {
  const selected = new Set(current.filter(key => validKeys.has(key)))
  for (const change of changes) {
    if (change.type !== 'select' || !validKeys.has(change.id)) continue
    if (change.selected) selected.add(change.id)
    else selected.delete(change.id)
  }
  return [...selected]
}

export function sameSelection(left: string[], right: string[]) {
  return left.length === right.length
    && left.every((key, index) => key === right[index])
}

export function selectionAfterNodeClick(current: string[], key: string, additive: boolean) {
  if (!additive) return [key]
  return current.includes(key)
    ? current.filter(item => item !== key)
    : [...current, key]
}

export function isAdditiveSelectionEvent(event: MouseEvent | TouchEvent) {
  return 'metaKey' in event && (event.metaKey || event.ctrlKey || event.shiftKey)
}

export function selectionGestureMoved(
  start: { x: number; y: number },
  current: { x: number; y: number },
  threshold = 3,
) {
  return Math.hypot(current.x - start.x, current.y - start.y) > threshold
}
