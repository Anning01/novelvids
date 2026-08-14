import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SceneVideoGenerationHistory from './SceneVideoGenerationHistory.vue'
import { TaskStatusEnum } from '@/types'
import type { Video } from '@/types'

function record(overrides: Partial<Video>): Video {
  return {
    id: 1,
    scene_id: 8,
    model_type: 1,
    status: TaskStatusEnum.COMPLETED,
    external_task_id: undefined,
    url: '/media/videos/1.mp4',
    metadata: {
      model_name: 'Seedance 2.5',
      duration: 6,
      aspect_ratio: '16:9',
      resolution: '720p',
    },
    created_at: '2026-08-14T10:20:00',
    updated_at: '2026-08-14T10:20:00',
    ...overrides,
  }
}

describe('SceneVideoGenerationHistory', () => {
  it('renders a compact version rail and allows switching to an older completed result', async () => {
    const current = record({ id: 3, created_at: '2026-08-14T10:30:00' })
    const previous = record({ id: 2, created_at: '2026-08-14T10:10:00', url: '/media/videos/2.mp4' })
    const wrapper = mount(SceneVideoGenerationHistory, {
      props: { records: [previous, current], currentId: current.id },
    })

    expect(wrapper.text()).not.toContain('生成记录')
    expect(wrapper.text()).toContain('当前分镜')
    expect(wrapper.text()).not.toContain('Seedance 2.5')
    expect(wrapper.findAll('.video-history__version')).toHaveLength(2)

    const restoreButton = wrapper.findAll('.video-history__version').find(button => button.attributes('aria-label')?.includes('版本 2'))
    await restoreButton?.trigger('click')
    expect(wrapper.emitted('select')).toEqual([[previous]])
  })

  it('keeps failed reason hidden until requested and emits retry from the compact dialog', async () => {
    const failed = record({
      id: 4,
      status: TaskStatusEnum.FAILED,
      url: undefined,
      metadata: { error: '上游 HTTP 400：参考图包含真人信息' },
    })
    const wrapper = mount(SceneVideoGenerationHistory, {
      props: { records: [failed], currentId: failed.id },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.text()).toContain('生成失败')
    expect(wrapper.text()).not.toContain('参考图包含真人信息')
    await wrapper.get('.video-history__version').trigger('click')
    expect(wrapper.get('[role="dialog"]').text()).toContain('参考图包含真人信息')
    await wrapper.get('.video-history-error-dialog__retry').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })
})
