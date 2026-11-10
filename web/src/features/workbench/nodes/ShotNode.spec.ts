import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import WorkbenchPromptEditorPanel from '../components/WorkbenchPromptEditorPanel.vue'
import { TaskStatusEnum } from '@/types'
import { createWorkbenchPromptActionRegistry, workbenchPromptActionRegistryKey } from '../prompt/promptActionRegistry'
import ShotNode from './ShotNode.vue'

const frameStub = {
  props: ['data'],
  template: '<article :data-kind="data.kind" :data-borderless="String(data.borderless_media)" :data-draggable="String(data.body_draggable)"><header><slot name="meta" /></header><div class="toolbar-actions"><slot name="toolbar-actions" /></div><slot /></article>',
}

const videoStub = {
  props: ['src', 'title', 'ratio'],
  emits: ['metadata'],
  template: '<button data-video-media :data-src="src" :data-title="title" :data-ratio="ratio" @click="$emit(\'metadata\', { width: 864, height: 496 })" />',
}

it('passes saved first-frame references to the canvas editor without requiring an asset edge', () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const syntax = '@{参考图片:uploads%2F1%2Flast-frame.png}'
  const wrapper = mount(ShotNode, {
    props: { id: 'shot-8', type: 'shot', selected: false, connectable: true,
      position: { x: 0, y: 0 }, dimensions: { width: 400, height: 300 }, dragging: false,
      resizing: false, zIndex: 0, events: {}, data: {
      scene: { id: 8, chapter_id: 1, sequence: 2, duration: 5, prompt: `首帧参考：${syntax}`,
        metadata: { video_reference_media: [{ type: 'image', name: '分镜1生成尾帧.png',
          url: 'https://cdn.example.com/last-frame.png', mention_url: 'uploads/1/last-frame.png' }] } },
      videos: [], videoModelOptions: [], prompt_editor_open: true,
      prompt_editor: { editorKey: 'shot_prompt', nodeKind: 'shot', fieldKey: 'prompt', label: '视频 Prompt', referenceLimits: {} },
    } } as never,
    global: { plugins: [pinia], stubs: { WorkbenchNodeFrame: frameStub,
      WorkbenchVideoMedia: videoStub, WorkbenchPromptEditorPanel: true } },
  })
  expect(wrapper.getComponent(WorkbenchPromptEditorPanel).props('mentions')).toEqual([
    expect.objectContaining({ name: '分镜1生成尾帧.png', mode: 'reference_image', syntax,
      previewUrl: 'https://cdn.example.com/last-frame.png' }),
  ])
  expect(wrapper.get('header').text()).toContain('图片 1/9')
})

it('presents a shot as a ratio-aware video card with media and asset metadata in the header', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const actionRegistry = createWorkbenchPromptActionRegistry()
  const wrapper = mount(ShotNode, {
    props: {
      id: 'scene-8',
      type: 'shot',
      selected: false,
      connectable: true,
      data: {
        scene: {
          id: 8,
          sequence: 1,
          duration: 5,
          metadata: {},
          created_at: '2026-08-15T00:00:00.000Z',
          updated_at: '2026-08-15T00:00:00.000Z',
        },
        videos: [{
          id: 21,
          scene_id: 8,
          model_type: 1,
          url: '/media/scene-8.mp4',
          status: TaskStatusEnum.COMPLETED,
          metadata: { duration: 5, aspect_ratio: '16:9', resolution: '720p' },
          created_at: '2026-08-15T00:00:00.000Z',
          updated_at: '2026-08-15T00:00:00.000Z',
        }],
        videoModelOptions: [],
        project_defaults: { aspectRatio: '16:9', resolution: '720p' },
        generate_capability: false,
      },
    } as never,
    global: {
      plugins: [pinia],
      provide: {
        [workbenchPromptActionRegistryKey as symbol]: actionRegistry,
      },
      stubs: {
        WorkbenchNodeFrame: frameStub,
        WorkbenchVideoMedia: videoStub,
        WorkbenchPromptEditorPanel: true,
      },
    },
  })

  expect(wrapper.get('article').attributes()).toMatchObject({
    'data-kind': 'shot',
    'data-borderless': 'true',
    'data-draggable': 'true',
  })
  expect(wrapper.get('[data-video-media]').attributes()).toMatchObject({
    'data-src': '/media/scene-8.mp4',
    'data-title': '视频 01',
    'data-ratio': '16:9',
  })
  expect(wrapper.get('.workbench-video-production').classes()).toContain('workbench-media-node')
  expect(wrapper.find('.workbench-video-enhancement').exists()).toBe(false)
  expect(wrapper.get('header').text()).toContain('720p · 16:9')
  expect(wrapper.get('header').text()).toContain('资产输入0 个')

  await wrapper.get('[data-video-media]').trigger('click')

  expect(wrapper.get('[data-video-media]').attributes('data-ratio')).toBe('864:496')
  expect(wrapper.get('header').text()).toContain('864 × 496')
  expect(wrapper.find('fieldset').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('生成参数')
  expect(wrapper.text()).not.toContain('视频版本')
  expect(actionRegistry.actions.get('scene-8')?.[0]?.controls?.map(control => control.id)).toEqual([
    'shot-video-generation-model',
    'shot-video-generation-parameters',
  ])

  const libraryButton = wrapper.get('.toolbar-actions button[aria-label="从资源库选择视频"]')
  expect(libraryButton.attributes('title')).toBe('从资源库选择视频')
  expect(libraryButton.text()).toBe('')
  expect(libraryButton.find('svg').exists()).toBe(true)
})
