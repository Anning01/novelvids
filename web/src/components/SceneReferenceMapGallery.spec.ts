import { mount, flushPromises } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import SceneReferenceMediaBar from './SceneReferenceMediaBar.vue'
import ImageLightbox from './ImageLightbox.vue'
import { catalogApi } from '@/features/resource-library/catalog'
import { fetchFileBlob } from '@/shared/downloadFile'
import type { Scene } from '@/types'

vi.mock('@/features/resource-library/catalog', () => ({catalogApi: {get: vi.fn()}}))
vi.mock('@/shared/downloadFile', () => ({fetchFileBlob: vi.fn()}))
const scene: Scene = {id: 4, sequence: 5, created_at: '', updated_at: ''}

it.each(['light', 'dark'])('shows only the sheet, map, upload and library selection in %s', async theme => {
  document.documentElement.dataset.appTheme = theme
  vi.mocked(catalogApi.get).mockResolvedValue({data: {url: '/media/library.png'}} as Awaited<ReturnType<typeof catalogApi.get>>)
  const wrapper = mount(SceneReferenceMediaBar, {props: {
    model: null, assetImageCount: 1,
    media: [
      {type: 'image', name: '线稿故事版', url: '/media/sheet.png'},
      {type: 'image', name: '用户上传', url: '/media/upload.png'},
      {type: 'image', name: '资源库图片', url: 'library.png', library_resource_id: 7},
    ],
    scene: {...scene, metadata: {imported_media: [{role:'blocking', url:'/media/work-packages/plan.svg'}]}},
  }})
  await flushPromises()
  const list = wrapper.get('.reference-media-bar .reference-list')
  expect(list.findAll('img').map(img => img.attributes('src'))).toEqual([
    '/media/sheet.png', '/media/upload.png', '/media/library.png', '/media/work-packages/plan.svg',
  ])
  await list.get('[data-reference-kind="blocking"] button').trigger('click')
  expect(wrapper.getComponent(ImageLightbox).props('src')).toBe('/media/work-packages/plan.svg')
  expect(wrapper.get('[role=status]').text()).toContain('图片 4/')
  await list.get('button[aria-label="移除 线稿故事版"]').trigger('click')
  expect(wrapper.emitted('remove')).toEqual([[0]])
  await wrapper.setProps({scene})
  expect(wrapper.find('[data-reference-kind="blocking"]').exists()).toBe(false)
  wrapper.unmount()
  delete document.documentElement.dataset.appTheme
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
