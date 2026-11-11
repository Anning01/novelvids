import { mount, flushPromises } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import SceneReferenceMediaBar from './SceneReferenceMediaBar.vue'
import ImageLightbox from './ImageLightbox.vue'
import { fetchFileBlob } from '@/shared/downloadFile'
import type { Scene } from '@/types'

vi.mock('@/shared/downloadFile', () => ({fetchFileBlob: vi.fn()}))
const scene: Scene = {id: 4, sequence: 5, created_at: '', updated_at: ''}

it('shows the imported blocking image on its shot, even without a structured plan', async () => {
  const wrapper = mount(SceneReferenceMediaBar, {props: {model: null, media:[{type:'image',name:'线稿故事版',url:'/media/sheet.png'}], assetImages:[{source:'asset',number:1,url:'/media/hero.png',label:'人物'}], scene: {...scene, metadata: {imported_media: [{role:'blocking', url:'/media/work-packages/plan.svg'}]}}}})
  const list = wrapper.get('.reference-media-bar .reference-list')
  expect(list.findAll('img').map(img => img.attributes('src'))).toEqual(['/media/hero.png', '/media/sheet.png','/media/work-packages/plan.svg'])
  await list.get('[data-reference-kind="blocking"] button').trigger('click')
  expect(wrapper.getComponent(ImageLightbox).props('src')).toBe('/media/work-packages/plan.svg')
  expect(wrapper.get('[role=status]').text()).toContain('图片 2/')
  await list.get('button[aria-label="移除 线稿故事版"]').trigger('click')
  expect(wrapper.emitted('remove')).toEqual([[0]])
  await wrapper.setProps({scene})
  expect(wrapper.find('[data-reference-kind="blocking"]').exists()).toBe(false)
  wrapper.unmount()
})

it('retrieves a structured multi-camera plan from the existing endpoint', async () => {
  vi.mocked(fetchFileBlob).mockResolvedValue(new Blob(['<svg/>'], {type:'image/svg+xml'}))
  const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:map')
  const release = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  const wrapper = mount(SceneReferenceMediaBar, {props:{model:null,media:[],scene:{...scene, prompt_params:{blocking_map:{}, segments:[{},{}]}}}})
  try {
    await flushPromises()
    expect(fetchFileBlob).toHaveBeenCalledWith('/api/scene/4/blocking-map.svg', expect.any(Object))
    expect(wrapper.get('img').attributes('src')).toBe('blob:map')
    await wrapper.setProps({scene})
    expect(release).toHaveBeenCalledWith('blob:map')
  } finally { wrapper.unmount(); create.mockRestore(); release.mockRestore() }
})
