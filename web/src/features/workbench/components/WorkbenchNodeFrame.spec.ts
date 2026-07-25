import { createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import type { WorkbenchNodeKind } from '../types/workbenchTypes'
import WorkbenchNodeFrame from './WorkbenchNodeFrame.vue'

const common = {
  id: 'node-1',
  selected: true,
  connectable: true,
}
const handleStub = {
  props: ['id'],
  template: '<i class="handle-stub" :data-id="id" />',
}

function mountFrame(kind: WorkbenchNodeKind) {
  return mount(WorkbenchNodeFrame, {
    props: { ...common, data: { title: kind, kind, status: 'ready' } },
    global: {
      plugins: [createPinia()],
      stubs: { Handle: handleStub, NodeInfoPanel: true },
    },
  })
}

it('uses centralized deletion capabilities for frame actions', () => {
  expect(mountFrame('asset').get('[aria-label="删除选中节点"]').attributes('disabled')).toBeUndefined()
  expect(mountFrame('chapter').get('[aria-label="删除选中节点"]').attributes('disabled')).toBeDefined()
})

it('renders the specialized watermark and composer ports', () => {
  expect(mountFrame('watermark').findAll('.handle-stub').map(handle => handle.attributes('data-id')))
    .toEqual(['video-input', 'watermark-output'])
  expect(mountFrame('video_composer').findAll('.handle-stub').map(handle => handle.attributes('data-id')))
    .toEqual(['shot-input', 'video-input', 'watermark-input', 'result-output'])
})
