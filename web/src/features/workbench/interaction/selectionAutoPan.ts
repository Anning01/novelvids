interface AutoPanPoint {
  x: number
  y: number
}

interface AutoPanBounds {
  width: number
  height: number
}

interface SelectionRect extends AutoPanPoint, AutoPanBounds {
  startX: number
  startY: number
}

function axisMovement(value: number, size: number, speed: number, edgeDistance: number) {
  if (value < edgeDistance) return Math.min(edgeDistance, Math.max(1, edgeDistance - value)) / edgeDistance * speed
  if (value > size - edgeDistance) return -Math.min(edgeDistance, Math.max(1, value - (size - edgeDistance))) / edgeDistance * speed
  return 0
}

export function selectionAutoPanDelta(point: AutoPanPoint, bounds: AutoPanBounds, speed = 15, edgeDistance = 40) {
  return {
    x: axisMovement(point.x, bounds.width, speed, edgeDistance),
    y: axisMovement(point.y, bounds.height, speed, edgeDistance),
  }
}

export function selectionRectAfterAutoPan(rect: SelectionRect, pointer: AutoPanPoint, delta: AutoPanPoint): SelectionRect {
  const startX = rect.startX + delta.x
  const startY = rect.startY + delta.y
  return {
    startX,
    startY,
    x: Math.min(pointer.x, startX),
    y: Math.min(pointer.y, startY),
    width: Math.abs(pointer.x - startX),
    height: Math.abs(pointer.y - startY),
  }
}
