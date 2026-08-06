import { useVueFlow } from '@vue-flow/core'
import { expect, it, vi } from 'vitest'
import * as runtime from './workbenchFlowRuntime'

const { flowInstance } = vi.hoisted(() => ({
  flowInstance: { id: 'bound-flow' },
}))

vi.mock('@vue-flow/core', () => ({
  useVueFlow: vi.fn(() => flowInstance),
}))

it('binds workbench helpers to the public flow id', () => {
  const useWorkbenchFlow = (runtime as typeof runtime & {
    useWorkbenchFlow?: () => unknown
  }).useWorkbenchFlow

  expect(useWorkbenchFlow).toBeTypeOf('function')
  if (!useWorkbenchFlow) return
  expect(useWorkbenchFlow()).toBe(flowInstance)
  expect(useVueFlow).toHaveBeenCalledWith('novel-workbench')
})

it('keeps selection enabled while locked', () => {
  const workbenchInteractionState = (runtime as typeof runtime & {
    workbenchInteractionState?: (
      locked: boolean,
      panModeActive: boolean,
    ) => {
      nodesDraggable: boolean
      nodesConnectable: boolean
      elementsSelectable: boolean
      panOnDrag: boolean
      selectNodesOnDrag: boolean
    }
  }).workbenchInteractionState

  expect(workbenchInteractionState).toBeTypeOf('function')
  if (!workbenchInteractionState) return
  expect(workbenchInteractionState(true, false)).toEqual({
    nodesDraggable: false,
    nodesConnectable: false,
    elementsSelectable: true,
    panOnDrag: true,
    selectNodesOnDrag: false,
  })
})
