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

it('supports borderless media presentation without removing selection feedback', () => {
  const wrapper = mount(WorkbenchNodeFrame, {
    props: { ...common, data: { title: '视频', kind: 'video_result', status: 'ready', borderless_media: true } },
    global: {
      plugins: [createPinia()],
      stubs: { Handle: handleStub, NodeInfoPanel: true },
    },
  })

  expect(wrapper.get('.workbench-node-frame').classes()).toEqual(expect.arrayContaining([
    'is-borderless-media',
    'is-selected',
  ]))
})

it('keeps a draggable header when a borderless node body contains interactive media', () => {
  const wrapper = mount(WorkbenchNodeFrame, {
    props: {
      ...common,
      data: {
        title: '视频',
        kind: 'shot',
        status: 'ready',
        borderless_media: true,
        floating_header: true,
      },
    },
    global: {
      plugins: [createPinia()],
      stubs: { Handle: handleStub, NodeInfoPanel: true },
    },
  })

  expect(wrapper.get('.workbench-node-frame__header').classes()).toContain('workbench-node-drag-handle')
  expect(wrapper.get('.workbench-node-frame__header').classes()).not.toContain('nodrag')
  expect(wrapper.get('.workbench-node-frame__body').classes()).toContain('nodrag')
})

it('allows media nodes to opt their body into dragging while controls remain isolated by nodrag descendants', () => {
  const wrapper = mount(WorkbenchNodeFrame, {
    props: {
      ...common,
      data: {
        title: '资产',
        kind: 'asset',
        status: 'ready',
        borderless_media: true,
        body_draggable: true,
      },
    },
    global: {
      plugins: [createPinia()],
      stubs: { Handle: handleStub, NodeInfoPanel: true },
    },
  })

  expect(wrapper.get('.workbench-node-frame__body').classes()).not.toContain('nodrag')
  expect(wrapper.get('.workbench-node-frame__body').classes()).toContain('workbench-node-frame__body--draggable')
})

it('uses centralized deletion capabilities for frame actions', () => {
  expect(mountFrame('asset').get('[aria-label="删除选中节点"]').attributes('disabled')).toBeUndefined()
  expect(mountFrame('chapter').get('[aria-label="删除选中节点"]').attributes('disabled')).toBeDefined()
})

it('renders the specialized watermark and composer ports', () => {
  expect(mountFrame('asset').findAll('.handle-stub').map(handle => handle.attributes('data-id')))
    .toEqual(['asset-input', 'asset-output'])
  expect(mountFrame('watermark').findAll('.handle-stub').map(handle => handle.attributes('data-id')))
    .toEqual(['watermark-video-input', 'watermark-output', 'output-output'])
  expect(mountFrame('video_composer').findAll('.handle-stub').map(handle => handle.attributes('data-id')))
    .toEqual(['shot-input', 'video-input', 'watermark-input', 'output-output'])
})
