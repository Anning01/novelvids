import { describe, expect, it } from 'vitest'
import { isWorkbenchFlowReady, WORKBENCH_FLOW_ID } from './workbenchFlowRuntime'

describe('workbench flow runtime', () => {
  it('uses the one public flow id', () => {
    expect(WORKBENCH_FLOW_ID).toBe('novel-workbench')
  })

  it('rejects an unmeasured viewport', () => {
    expect(isWorkbenchFlowReady({ width: 0, height: 720 })).toBe(false)
    expect(isWorkbenchFlowReady({ width: 1280, height: 720 })).toBe(true)
  })
})
