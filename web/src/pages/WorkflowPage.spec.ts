import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { expect, it, vi } from 'vitest'
import { api } from '@/api'
import type { WorkbenchBootstrap, SingleResponse } from '@/types'
import WorkflowPage from './WorkflowPage.vue'

vi.mock('@/features/workbench/pages/CreativeCanvas.vue', () => ({
  default: { name: 'CanvasProbe', props: ['bootstrap'], template: '<main class="test-canvas" />' },
}))

function reply(id: number): SingleResponse<WorkbenchBootstrap> {
  return { code: 0, message: 'ok', data: {
    chapter: { id, number: id, novel_id: 7, name: 'Chapter ' + id, created_at: '', updated_at: '' },
    scenes: [], assets: [], videos: {},
  } }
}

it('shares the route request with the canvas, discards a late chapter and retries a failed open', async () => {
  let resolveFirst!: (value: SingleResponse<WorkbenchBootstrap>) => void
  const first = new Promise<SingleResponse<WorkbenchBootstrap>>(resolve => { resolveFirst = resolve })
  const bootstrap = vi.spyOn(api, 'workbenchBootstrap').mockReturnValueOnce(first)
    .mockRejectedValueOnce(new Error('chapter unavailable')).mockResolvedValueOnce(reply(2))
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/novel/:novelId', component: {template: '<div />'} },
    { path: '/novel/:novelId/chapter/:chapterId/step/:stepId', component: WorkflowPage },
  ] })
  await router.push('/novel/7/chapter/1/step/3')
  const wrapper = mount(RouterView, { global: { plugins: [router], stubs: { AppButton: { template: '<button><slot /></button>' } } } })
  try {
    await vi.waitFor(() => expect(wrapper.find('.test-canvas').exists()).toBe(true))
    expect(wrapper.getComponent({ name: 'CanvasProbe' }).props('bootstrap')).toBe(first)
    expect(bootstrap).toHaveBeenCalledTimes(1)
    await router.push('/novel/7/chapter/2/step/1')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('chapter unavailable')
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    resolveFirst(reply(1))
    await flushPromises()
    expect(wrapper.get('.workflow-back strong').text()).toBe('Chapter 2')
    expect(bootstrap).toHaveBeenCalledTimes(3)
  } finally {
    wrapper.unmount()
    bootstrap.mockRestore()
  }
})
