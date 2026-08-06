import type { WorkbenchNode } from '../types/workbenchTypes'

export const PINNED_NODE_Z_INDEX_BASE = 1_000_000

export function isPinnedNode(node: Pick<WorkbenchNode, 'zIndex'> | null | undefined) {
  return Number(node?.zIndex ?? 0) >= PINNED_NODE_Z_INDEX_BASE
}

export function nextPinnedNodeZIndex(nodes: ReadonlyArray<Pick<WorkbenchNode, 'zIndex'>>) {
  return Math.max(
    PINNED_NODE_Z_INDEX_BASE - 1,
    ...nodes.filter(isPinnedNode).map(node => Number(node.zIndex) || 0),
  ) + 1
}

export function nextRegularNodeZIndex(nodes: ReadonlyArray<Pick<WorkbenchNode, 'zIndex'>>) {
  return Math.max(
    0,
    ...nodes.filter(node => !isPinnedNode(node)).map(node => Number(node.zIndex) || 0),
  ) + 1
}
