import { mount, flushPromises } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import SceneBlockingMap from './SceneBlockingMap.vue'
import { fetchFileBlob } from '@/shared/downloadFile'
import type { Scene } from '@/types'

vi.mock('@/shared/downloadFile', () => ({fetchFileBlob: vi.fn()}))
const scene: Scene = {id: 4, sequence: 5, created_at: '', updated_at: ''}

it('shows the imported blocking image on its shot, even without a structured plan', async () => {
  const wrapper = mount(SceneBlockingMap, {props: {scene: {...scene, metadata: {imported_media: [{role:'blocking', url:'/media/work-packages/plan.svg'}]}}}})
  expect(wrapper.get('img').attributes('src')).toBe('/media/work-packages/plan.svg')
  await wrapper.setProps({scene})
  expect(wrapper.find('figure').exists()).toBe(false)
  wrapper.unmount()
})

it('retrieves a structured multi-camera plan from the existing endpoint', async () => {
  vi.mocked(fetchFileBlob).mockResolvedValue(new Blob(['<svg/>'], {type:'image/svg+xml'}))
  const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:map')
  const release = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  const wrapper = mount(SceneBlockingMap, {props:{scene:{...scene, prompt_params:{blocking_map:{}, segments:[{},{}]}}}})
  try {
    await flushPromises()
    expect(fetchFileBlob).toHaveBeenCalledWith('/api/scene/4/blocking-map.svg', expect.any(Object))
    expect(wrapper.get('img').attributes('src')).toBe('blob:map')
    await wrapper.setProps({scene})
    expect(release).toHaveBeenCalledWith('blob:map')
  } finally { wrapper.unmount(); create.mockRestore(); release.mockRestore() }
})
