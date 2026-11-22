import { mount } from '@vue/test-utils'
import { BaseEdge, Position, getBezierPath } from '@vue-flow/core'
import { expect, it } from 'vitest'
import AssetReferenceEdge from './AssetReferenceEdge.vue'
import OutputBindingEdge from './OutputBindingEdge.vue'
import ShotSequenceEdge from './ShotSequenceEdge.vue'

it.each([AssetReferenceEdge, OutputBindingEdge, ShotSequenceEdge])('follows the original Bézier curve when the target moves behind the source', async component => {
  const ports = { sourceX: 100, sourceY: 140, sourcePosition: Position.Right,
    targetX: 400, targetY: 90, targetPosition: Position.Left }
  const wrapper = mount(component, {
    props: { id: 'wire', source: 'a', target: 'b', ...ports } as never,
    global: { stubs: { BaseEdge: true } },
  })
  expect(wrapper.getComponent(BaseEdge).props('path')).toBe(getBezierPath(ports)[0])
  await wrapper.setProps({ targetX: -200, targetY: 320 })
  expect(wrapper.getComponent(BaseEdge).props('path')).toBe(getBezierPath({ ...ports, targetX: -200, targetY: 320 })[0])
  wrapper.unmount()
})
