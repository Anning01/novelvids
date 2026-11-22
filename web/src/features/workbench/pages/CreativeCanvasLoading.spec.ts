import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { useWorkbenchStore } from '../store/workbenchStore'
import CreativeCanvas from './CreativeCanvas.vue'

afterEach(() => vi.restoreAllMocks())

it('can retry a standalone canvas without a chapter request from the workflow page', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const load = vi.spyOn(useWorkbenchStore(), 'load').mockRejectedValueOnce(new Error('workspace offline')).mockResolvedValueOnce()
  vi.spyOn(api, 'workbenchCapabilities').mockRejectedValue(new Error('offline'))
  const wrapper = shallowMount(CreativeCanvas, {
    props: { novelId: 7, chapterId: 8 },
    global: { plugins: [pinia], stubs: { AppButton: { template: '<button><slot /></button>' } } },
  })
  try {
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('workspace offline')
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(load.mock.calls).toEqual([[7, 8, undefined], [7, 8, undefined]])
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  } finally {
    wrapper.unmount()
  }
})
