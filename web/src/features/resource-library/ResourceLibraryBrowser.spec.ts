import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { appConfirm } from '@/shared/confirmDialog'
import { useAuthStore } from '@/features/auth/authStore'
import { libraryApi } from './api'
import ResourceLibraryBrowser from './ResourceLibraryBrowser.vue'
import type { VideoResource } from './types'

vi.mock('@/shared/confirmDialog', () => ({ appConfirm: vi.fn() }))
vi.mock('./api', () => ({ libraryApi: {
  capabilities: vi.fn(), folders: vi.fn(), list: vi.fn(), move: vi.fn(), upload: vi.fn(),
  delete: vi.fn(), writeFolder: vi.fn(), rename: vi.fn(), deletePreview: vi.fn(), deleteFolder: vi.fn(),
} }))
const video: VideoResource = { id: 1, folder_id: 0, name: '动作参考', filename: 'motion.mp4', url: '/media/a.mp4', storage_ref: '/media/a.mp4', poster_url: '/media/a.jpg', state: 'ready', created_at: '', duration: 3, width: 1280, height: 720, fps: 24, codec: 'h264', content_type: 'video/mp4', size_bytes: 100 }
const button = { template: '<button :disabled="$attrs.disabled"><slot /></button>' }
function render(pick = false) {
  return mount(ResourceLibraryBrowser, { props: { pick }, global: { stubs: { AppButton: button, ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /></div>' } } } })
}
const response = (items: VideoResource[]) => ({ code: 0, message: '', data: { items, pagination: { total: items.length, page: 1, page_size: 24, pages: 1 } } })
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(libraryApi.upload).mockReset()
  setActivePinia(createPinia())
  useAuthStore().enabled = false
  vi.mocked(libraryApi.capabilities).mockResolvedValue({ code: 0, message: '', data: { formats: ['mp4', 'mov'], max_size_mb: 200, folder_depth: 2 } })
  vi.mocked(libraryApi.folders).mockResolvedValue({ code: 0, message: '', data: [{ id: 10, parent_id: 0, name: '角色', deleting: false }] })
  vi.mocked(libraryApi.list).mockImplementation(async () => response([video]))
  vi.mocked(libraryApi.move).mockResolvedValue({})
})

it('selects once, shows folder destination and moves through a button', async () => {
  const wrapper = render(); await flushPromises()
  await wrapper.get('input[type="checkbox"]').setValue(true)
  const move = wrapper.findAll('button').find(item => item.text() === '移动到')!
  await move.trigger('click')
  await wrapper.get('[aria-label="目标文件夹"]').trigger('click')
  await flushPromises()
  const option = document.body.querySelector<HTMLButtonElement>('[role="option"]:last-child')!
  option.click()
  await flushPromises()
  await wrapper.findAll('form').at(-1)!.trigger('submit')
  await flushPromises()
  expect(libraryApi.move).toHaveBeenCalledWith([1], 10)
  expect(wrapper.text()).toContain('已选 0 个')
})

it('moves a dragged card to a folder with the same batch operation', async () => {
  const wrapper = render(); await flushPromises()
  await wrapper.get('article').trigger('dragstart')
  await wrapper.get('.library-folder-row').trigger('drop')
  await flushPromises()
  expect(libraryApi.move).toHaveBeenCalledWith([1], 10)
})

it('pins upload folder even when browsing changes before completion', async () => {
  let finish: ((value: VideoResource) => void) | undefined
  vi.mocked(libraryApi.upload).mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const wrapper = render(); await flushPromises()
  await wrapper.get('.library-folder-row>button').trigger('click'); await flushPromises()
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: [new File(['clip'], 'clip.mp4', { type: 'video/mp4' })] })
  await input.trigger('change'); await flushPromises()
  await wrapper.get('.library-folders>button').trigger('click'); await flushPromises()
  expect(libraryApi.upload).toHaveBeenCalledWith(expect.any(File), 10, expect.any(Function))
  finish?.(video); await flushPromises()
  expect(wrapper.text()).toContain('保存到：角色')
})

it('picker deduplicates selections and clears them when team changes', async () => {
  const wrapper = render(true); await flushPromises()
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await wrapper.findAll('button').find(item => item.text().includes('使用所选视频'))!.trigger('click')
  expect(wrapper.emitted('choose')?.[0]?.[0]).toEqual([video])
  useAuthStore().activeTeamId = 2
  await flushPromises()
  expect(wrapper.text()).toContain('已选 0 个')
  expect(wrapper.get<HTMLInputElement>('input[type="checkbox"]').element.checked).toBe(false)
})

it('ignores a stale list response after switching teams', async () => {
  let finish: ((value: ReturnType<typeof response>) => void) | undefined
  vi.mocked(libraryApi.list).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const wrapper = render(); await flushPromises()
  useAuthStore().activeTeamId = 2; await flushPromises()
  finish?.(response([{ ...video, id: 99, name: '前团队素材' }])); await flushPromises()
  expect(wrapper.text()).not.toContain('前团队素材')
  expect(wrapper.text()).toContain('动作参考')
})

it('hides management controls for read-only team members', async () => {
  const auth = useAuthStore(); auth.enabled = true
  auth.memberships = [{ team_id: 1, role: 'viewer' } as typeof auth.memberships[number]]
  auth.activeTeamId = 1
  const wrapper = render(); await flushPromises()
  expect(wrapper.text()).not.toContain('上传视频')
  expect(wrapper.text()).not.toContain('移动到')
  expect(wrapper.find('input[type="file"]').exists()).toBe(false)
})

it('searches all folders while showing each result location', async () => {
  const wrapper = render(); await flushPromises()
  await wrapper.get('.library-folder-row>button').trigger('click'); await flushPromises()
  await wrapper.get('.library-search input').setValue('动作')
  await wrapper.get('.library-search').trigger('submit'); await flushPromises()
  expect(libraryApi.list).toHaveBeenLastCalledWith(10, '动作', 1)
  expect(wrapper.text()).toContain('未分类')
})


it('shows a retryable failure instead of reporting a partial deletion as success', async () => {
  vi.mocked(appConfirm).mockResolvedValue(true)
  vi.mocked(libraryApi.delete).mockResolvedValue({ code: 0, message: '', data: [{ id: 1, deleted: false, error: 'storage failed' }] })
  const wrapper = render(); await flushPromises()
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await wrapper.findAll('button').find(item => item.text() === '删除')!.trigger('click')
  await flushPromises()
  expect(libraryApi.delete).toHaveBeenCalledWith([1])
  expect(wrapper.get('[role="alert"]').text()).toContain('删除失败')
  expect(appConfirm).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('不可恢复') }))
})

it('marks only the current folder and keeps its menu control on the same row', async () => {
  const wrapper = render(); await flushPromises()
  expect(wrapper.findAll('[aria-current="page"]')).toHaveLength(1)
  expect(wrapper.get('[aria-current="page"]').text()).toBe('全部视频')
  const row = wrapper.get('.library-folder-row')
  expect(row.find('summary svg').exists()).toBe(true)
  expect(row.get('summary').text()).toBe('')
  await row.get('button').trigger('click'); await flushPromises()
  expect(wrapper.findAll('[aria-current="page"]')).toHaveLength(1)
  expect(wrapper.get('[aria-current="page"]').text()).toBe('角色')
  expect(row.classes()).toContain('active')
  await wrapper.get('.library-folders>button:nth-child(2)').trigger('click'); await flushPromises()
  expect(wrapper.get('[aria-current="page"]').text()).toBe('未分类')
  expect(row.classes()).not.toContain('active')
})

it('closes the folder menu on outside click, navigation, Escape and menu actions', async () => {
  const wrapper = render(); await flushPromises()
  const menu = wrapper.get<HTMLDetailsElement>('.folder-menu')
  menu.element.open = true
  document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
  expect(menu.element.open).toBe(false)
  menu.element.open = true
  await wrapper.get('.library-folders>button').trigger('click')
  expect(menu.element.open).toBe(false)
  menu.element.open = true
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(menu.element.open).toBe(false)
  menu.element.open = true
  await menu.findAll('button')[0]!.trigger('click')
  await flushPromises()
  expect(menu.element.open).toBe(false)
  expect(wrapper.get('.library-form input').element).toBeTruthy()
  wrapper.unmount()
})

it('opens the real folder dialog and video preview, and supports closing and reopening', async () => {
  const wrapper = mount(ResourceLibraryBrowser, { attachTo: document.body, global: { stubs: { AppButton: button } } })
  await flushPromises()
  await wrapper.findAll('button').find(item => item.text() === '新建文件夹')!.trigger('click')
  await flushPromises()
  let dialog = document.body.querySelector<HTMLElement>('.resource-library-dialog[role="dialog"]')
    || document.body.querySelector<HTMLElement>('.resource-library-dialog')
  expect(dialog).not.toBeNull()
  expect(dialog?.textContent).toContain('文件夹名称')
  dialog?.querySelector<HTMLButtonElement>('.el-dialog__headerbtn')?.click()
  await flushPromises()
  await wrapper.get('[aria-label="预览 动作参考"]').trigger('click')
  await flushPromises()
  expect(document.body.querySelector('video')?.getAttribute('src')).toBe('/media/a.mp4')
  expect(document.body.querySelector('video')?.controls).toBe(true)
  wrapper.unmount()
})

it('uses the shared selector above the dialog and submits numeric parent IDs', async () => {
  vi.mocked(libraryApi.writeFolder).mockResolvedValue({ code: 0, message: '', data: { id: 11, parent_id: 10, name: '子目录', deleting: false } })
  const wrapper = render(); await flushPromises()
  await wrapper.findAll('button').find(item => item.text() === '新建文件夹')!.trigger('click')
  await wrapper.get('.library-form input').setValue('子目录')
  expect(wrapper.find('select').exists()).toBe(false)
  await wrapper.get('[aria-label="上级目录"]').trigger('click'); await flushPromises()
  const menu = document.body.querySelector<HTMLElement>('[role="listbox"]')!
  expect(menu.style.zIndex).toBe('3000')
  const option = Array.from(menu.querySelectorAll<HTMLButtonElement>('[role="option"]')).find(item => item.textContent?.includes('角色'))!
  option.click(); await flushPromises()
  await wrapper.get('.library-form').trigger('submit'); await flushPromises()
  expect(libraryApi.writeFolder).toHaveBeenCalledWith('子目录', 10, undefined)
})

it('shows upload preparation, real progress, processing and a lasting success result', async () => {
  let progress: ((value: number) => void) | undefined
  let finish: ((value: VideoResource) => void) | undefined
  vi.mocked(libraryApi.upload).mockImplementation((_file, _folder, onProgress) => {
    progress = onProgress
    return new Promise(resolve => { finish = resolve })
  })
  const wrapper = render(); await flushPromises()
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: [new File(['clip'], 'clip.mp4', { type: 'video/mp4' })] })
  await input.trigger('change'); await flushPromises()
  expect(wrapper.text()).toContain('正在准备上传')
  expect(wrapper.find('.library-empty').exists()).toBe(false)
  progress?.(37); await flushPromises()
  expect(wrapper.text()).toContain('上传中 37%')
  expect(wrapper.get('.library-upload-job progress').attributes('value')).toBe('37')
  progress?.(100); await flushPromises()
  expect(wrapper.text()).toContain('正在校验视频并生成封面')
  expect(wrapper.get('.library-upload-job progress').attributes('value')).toBeUndefined()
  finish?.(video); await flushPromises()
  expect(wrapper.text()).toContain('上传成功，已存入资源库')
  expect(wrapper.text()).toContain('上传结束：成功 1 个，失败 0 个')
  await wrapper.findAll('button').find(item => item.text() === '完成')!.trigger('click')
  expect(wrapper.find('.library-upload-panel').exists()).toBe(false)
  expect(wrapper.get('.library-upload-summary').text()).toContain('成功 1 个')
  await wrapper.findAll('button').find(item => item.text() === '查看上传详情')!.trigger('click')
  expect(wrapper.find('.library-upload-panel').exists()).toBe(true)
})

it('keeps failed upload details visible and retries successfully without losing the destination', async () => {
  vi.mocked(libraryApi.upload).mockRejectedValueOnce(new Error('网络连接断开')).mockResolvedValueOnce(video)
  const wrapper = render(); await flushPromises()
  await wrapper.get('.library-folder-row>button').trigger('click'); await flushPromises()
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: [new File(['clip'], 'clip.mp4')] })
  await input.trigger('change'); await flushPromises()
  expect(wrapper.text()).toContain('上传失败')
  expect(wrapper.get('.library-upload-panel [role="alert"]').text()).toBe('网络连接断开')
  await wrapper.findAll('button').find(item => item.text() === '重试上传')!.trigger('click'); await flushPromises()
  expect(libraryApi.upload).toHaveBeenLastCalledWith(expect.any(File), 10, expect.any(Function))
  expect(wrapper.text()).toContain('上传成功，已存入资源库')
  expect(wrapper.find('.library-upload-panel [role="alert"]').exists()).toBe(false)
})

it('reports invalid selected files in the upload dialog without a silent return', async () => {
  const wrapper = render(); await flushPromises()
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: [new File(['image'], 'wrong.png')] })
  await input.trigger('change'); await flushPromises()
  expect(wrapper.get('.library-upload-panel [role="alert"]').text()).toContain('仅支持非空 MP4/MOV')
  expect(wrapper.text()).toContain('成功 0 个，失败 1 个')
  expect(libraryApi.upload).not.toHaveBeenCalled()
})

it('keeps the picker compact with actions beside search and no duplicated page heading', async () => {
  const wrapper = render(true); await flushPromises()
  expect(wrapper.find('.library-heading').exists()).toBe(false)
  expect(wrapper.find('h1').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('跨项目共享视频，移动文件不会改变引用地址')
  const toolbar = wrapper.get('.library-toolbar')
  expect(toolbar.find('.library-search').exists()).toBe(true)
  expect(toolbar.text()).toContain('新建文件夹')
  expect(toolbar.text()).toContain('上传视频')
  expect(wrapper.find('input[type="file"]').exists()).toBe(true)
  await toolbar.findAll('button').find(item => item.text() === '新建文件夹')!.trigger('click')
  await flushPromises()
  expect(wrapper.find('.library-form input').exists()).toBe(true)
})
