import type { WorkbenchNode } from '../types/workbenchTypes'

// Keep the same marker values as shengshimedia so saved canvas colors round-trip.
export const WORKBENCH_NODE_MARKER_COLORS = ['#a995ff', '#df7f73', '#dfb75f', '#70a98a', '#6d99c7', '#d584b8'] as const
export const DEFAULT_SECTION_COLOR = '#31558f'

export function nodeMarkerColor(node: WorkbenchNode) {
  const color = node.kind === 'section' || node.kind === 'note' ? node.data.color : node.data.ui?.color
  return typeof color === 'string' ? color : ''
}

export function commonMarkerColor(nodes: WorkbenchNode[]) {
  const first = nodes[0] && nodeMarkerColor(nodes[0])
  return first && nodes.every(node => nodeMarkerColor(node) === first) ? first : ''
}
