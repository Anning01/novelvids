import type { NodeSize, Point } from '../types/workbenchTypes'

export function screenPointForCenteredNode(
  bounds: { left: number; top: number; width: number; height: number },
  size: NodeSize,
  zoom = 1,
) {
  return {
    x: Math.round(bounds.left + Math.max(24, (bounds.width - size.width * zoom) / 2)),
    y: Math.round(bounds.top + Math.max(64, (bounds.height - size.height * zoom) / 2)),
  }
}

/** Keep the first working card legible, with its floating title above the card. */
export function initialCardViewport(canvas: NodeSize, position: Point, size: NodeSize, bottomInset: number) {
  const sideInset = 20
  const topInset = 56
  const zoom = Math.min(1, Math.max(0.65, (canvas.width - 2 * sideInset) / size.width))
  const availableHeight = canvas.height - topInset - bottomInset
  return {
    x: (canvas.width - size.width * zoom) / 2 - position.x * zoom,
    y: topInset + Math.max(0, (availableHeight - size.height * zoom) / 2) - position.y * zoom,
    zoom,
  }
}
