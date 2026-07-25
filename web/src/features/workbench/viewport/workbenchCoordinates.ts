export function screenPointForCenteredNode(
  bounds: { left: number; top: number; width: number; height: number },
  size: { width: number; height: number },
) {
  return {
    x: Math.round(bounds.left + Math.max(24, (bounds.width - size.width) / 2)),
    y: Math.round(bounds.top + Math.max(64, (bounds.height - size.height) / 2)),
  }
}
