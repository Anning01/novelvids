import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ChapterExportPanel from './ChapterExportPanel.vue'
import { exportApi, type ChapterExport } from './api'
import { appConfirm } from '@/shared/confirmDialog'
import { downloadFile, fetchFileBlob } from '@/shared/downloadFile'
import { useAuthStore } from '@/features/auth/authStore'

vi.mock('@/shared/confirmDialog', () => ({ appConfirm: vi.fn() }))
vi.mock('@/shared/downloadFile', () => ({ downloadFile: vi.fn(), fetchFileBlob: vi.fn() }))

const source: ChapterExport = { id: 1, chapter_id: 2, parent_export_id: null, source_version: 'a'.repeat(64),
  source_sha256: 'b'.repeat(64), source_probe: { width: 864, height: 496, duration: 5, fps: 24 },
  output_probe: {}, source_url: '/media/source.mp4', url: '/media/source.mp4', task_id: 'task', status: 3,
  stage: 'completed', error: null, created_at: '', recipe: {} }

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(exportApi, 'list').mockResolvedValue({ data: [source] })
  vi.spyOn(exportApi, 'models').mockResolvedValue({ data: [{ id: 8, name: 'MediaKit' }] })
})

describe('ChapterExportPanel', () => {
  it('preparing and downloading a source never trigger paid enhancement', async () => {
    vi.spyOn(exportApi, 'prepare').mockResolvedValue({ data: { export_id: 1, task_id: 'task', status: 1 } })
    const enhance = vi.spyOn(exportApi, 'enhance')
    const wrapper = mount(ChapterExportPanel, { props: { chapterId: 2 }, global: { plugins: [createPinia()] } })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('准备当前原片'))!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('下载原片'))!.trigger('click')
    expect(enhance).not.toHaveBeenCalled()
    expect(appConfirm).not.toHaveBeenCalled()
    expect(downloadFile).toHaveBeenCalledWith('/api/video/exports/1/download?source=true', expect.any(String), {})
    wrapper.unmount()
  })

  it('submits exactly the quoted source only after explicit confirmation', async () => {
    const quote = { amount: '0.416667', currency: 'CNY', source_sha256: source.source_sha256!, quote_version: 'c'.repeat(64) }
    vi.spyOn(exportApi, 'quote').mockResolvedValue({ data: quote })
    vi.mocked(appConfirm).mockResolvedValue(true)
    const enhance = vi.spyOn(exportApi, 'enhance').mockResolvedValue({ data: { export_id: 3, task_id: 'enhance', status: 1 } })
    const wrapper = mount(ChapterExportPanel, { props: { chapterId: 2 }, global: { plugins: [createPinia()] } })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('增强到1080p'))!.trigger('click')
    await flushPromises()
    expect(appConfirm).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('0.416667') }))
    expect(enhance).toHaveBeenCalledExactlyOnceWith(1, 8, quote)
    wrapper.unmount()
  })

  it('rejects stale confirmation after changing chapters and hides write actions from viewers', async () => {
    let resolveConfirmation: (result: boolean) => void = () => {}
    vi.mocked(appConfirm).mockImplementation(() => new Promise(resolve => { resolveConfirmation = resolve }))
    vi.spyOn(exportApi, 'quote').mockResolvedValue({ data: { amount: '1', currency: 'CNY', source_sha256: 'a', quote_version: 'b' } })
    const enhance = vi.spyOn(exportApi, 'enhance')
    const pinia = createPinia()
    const wrapper = mount(ChapterExportPanel, { props: { chapterId: 2 }, global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('增强到1080p'))!.trigger('click')
    await flushPromises()
    await wrapper.setProps({ chapterId: 3 })
    resolveConfirmation(true)
    await flushPromises()
    expect(enhance).not.toHaveBeenCalled()
    const auth = useAuthStore(pinia)
    auth.$patch({ enabled: true, user: { id: 1, username: 'viewer', is_super_admin: false, nickname: '', avatar_url: '' }, activeTeamId: 1,
      memberships: [{ team_id: 1, team_name: 'Team', role: 'viewer' }] })
    await flushPromises()
    expect(wrapper.text()).not.toContain('准备当前原片')
    expect(wrapper.text()).not.toContain('增强到1080p')
    wrapper.unmount()
  })

  it('shows saving and failure states while keeping the source downloadable', async () => {
    vi.mocked(exportApi.list).mockResolvedValue({ data: [{ ...source, id: 3, parent_export_id: 1, status: 2, stage: 'saving_result', url: null },
      { ...source, id: 4, parent_export_id: 1, status: 4, stage: 'failed', error: 'Provider rejected', url: null },
      { ...source, id: 5, parent_export_id: 1, status: 5, stage: 'review_closed', url: null }] })
    const wrapper = mount(ChapterExportPanel, { props: { chapterId: 2 }, global: { plugins: [createPinia()] } })
    await flushPromises()
    expect(wrapper.text()).toContain('正在保存高清成片')
    expect(wrapper.text()).toContain('Provider rejected')
    expect(wrapper.find('.spin').exists()).toBe(true)
    expect(wrapper.text()).toContain('后续步骤已停止，已人工核对')
    expect(wrapper.findAll('button').filter(button => button.text().includes('下载原片'))).toHaveLength(3)
    wrapper.unmount()
  })
})

it('explains free reuse and restores keyboard focus after cancelling confirmation', async () => {
  vi.spyOn(exportApi, 'quote').mockResolvedValue({ data: {
    amount: '0', currency: 'CNY', source_sha256: source.source_sha256!, quote_version: 'c'.repeat(64), reused_export_id: 3,
  } })
  vi.mocked(appConfirm).mockResolvedValue(false)
  const enhance = vi.spyOn(exportApi, 'enhance')
  const wrapper = mount(ChapterExportPanel, { attachTo: document.body, props: { chapterId: 2 }, global: { plugins: [createPinia()] } })
  await flushPromises()
  const trigger = wrapper.findAll('button').find(button => button.text().includes('增强到1080p'))!
  ;(trigger.element as HTMLButtonElement).focus()
  await trigger.trigger('click')
  await flushPromises()
  expect(appConfirm).toHaveBeenCalledWith(expect.objectContaining({
    message: expect.stringContaining('不产生新增增强费用'), confirmLabel: '使用已有高清版',
  }))
  expect(enhance).not.toHaveBeenCalled()
  expect(document.activeElement).toBe(trigger.element)
  wrapper.unmount()
  wrapper.element.remove()
})

it('prepares one video without asking to complete the chapter and blocks 1080p sources', async () => {
  vi.spyOn(exportApi, 'listVideo').mockResolvedValueOnce({ data: [] }).mockResolvedValue({ data: [{ ...source, source_video_id: 9 }] })
  const prepare = vi.spyOn(exportApi, 'prepareVideo').mockResolvedValue({ data: { export_id: 1, task_id: 'task', status: 1 } })
  const enhance = vi.spyOn(exportApi, 'enhance')
  const wrapper = mount(ChapterExportPanel, { props: { videoId: 9 }, global: { plugins: [createPinia()] } })
  await flushPromises()
  expect(prepare).toHaveBeenCalledExactlyOnceWith(9)
  expect(exportApi.list).not.toHaveBeenCalled()
  expect(enhance).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('无需等本集完成')
  vi.mocked(exportApi.listVideo).mockResolvedValue({ data: [{ ...source, source_probe: { width: 1920, height: 1080, duration: 5, fps: 24 } }] })
  await wrapper.get('[aria-label="刷新导出记录"]').trigger('click')
  await flushPromises()
  const button = wrapper.findAll('button').find(item => item.text().includes('无需高清化'))!
  expect(button.attributes('disabled')).toBeDefined()
  wrapper.unmount()
})

it('previews the saved HD file through the authenticated endpoint and releases its blob URL', async () => {
  vi.mocked(exportApi.list).mockResolvedValue({ data: [{ ...source, id: 3, parent_export_id: 1 }] })
  vi.mocked(fetchFileBlob).mockResolvedValue(new Blob(['video'], { type: 'video/mp4' }))
  const create = vi.fn().mockReturnValue('blob:hd-preview')
  const revoke = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke })
  const wrapper = mount(ChapterExportPanel, { props: { chapterId: 2 }, global: { plugins: [createPinia()] } })
  try {
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '预览高清版')!.trigger('click')
    await flushPromises()
    expect(fetchFileBlob).toHaveBeenCalledWith('/api/video/exports/3/download', {})
    expect(wrapper.get('.export-preview video').attributes('src')).toBe('blob:hd-preview')
    expect(wrapper.get('.export-preview video').attributes('controls')).toBeDefined()
    await wrapper.findAll('button').find(button => button.text() === '关闭预览')!.trigger('click')
    expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:hd-preview')
    expect(wrapper.find('.export-preview video').exists()).toBe(false)
  } finally { wrapper.unmount(); vi.unstubAllGlobals() }
})
