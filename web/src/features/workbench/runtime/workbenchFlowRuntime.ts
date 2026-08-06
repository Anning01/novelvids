import { useVueFlow } from '@vue-flow/core'

export const WORKBENCH_FLOW_ID = 'novel-workbench' as const

export function useWorkbenchFlow() {
  return useVueFlow(WORKBENCH_FLOW_ID)
}

export function isWorkbenchFlowReady(dimensions: { width: number; height: number }) {
  return Number.isFinite(dimensions.width)
    && Number.isFinite(dimensions.height)
    && dimensions.width > 0
    && dimensions.height > 0
}

export function workbenchInteractionState(locked: boolean, panModeActive: boolean) {
  return {
    nodesDraggable: !locked && !panModeActive,
    nodesConnectable: !locked,
    elementsSelectable: true,
    panOnDrag: locked || panModeActive,
    selectNodesOnDrag: false,
  }
}
