export const WORKBENCH_FLOW_ID = 'novel-workbench' as const

export function isWorkbenchFlowReady(dimensions: { width: number; height: number }) {
  return Number.isFinite(dimensions.width)
    && Number.isFinite(dimensions.height)
    && dimensions.width > 0
    && dimensions.height > 0
}
