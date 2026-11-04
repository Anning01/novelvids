import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { editorApi } from './api'
import { editorFixture } from './fixtures'
import EditorWorkspace from './EditorWorkspace.vue'
import EditorLibrary from './EditorLibrary.vue'
import EditorTimeline from './EditorTimeline.vue'
import EditorPreview from './EditorPreview.vue'
import EditorInspector from './EditorInspector.vue'
import { useAuthStore } from '@/features/auth/authStore'

vi.mock('./api', () => ({ editorApi: { get: vi.fn(), save: vi.fn(), capabilities: vi.fn(), history: vi.fn(), export: vi.fn(), upload: vi.fn(), cancel: vi.fn() } }))
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear()
  vi.mocked(editorApi.get).mockResolvedValue({ data: editorFixture() } as never)
  vi.mocked(editorApi.capabilities).mockResolvedValue({ data: { formats: { video: ['mp4'], audio: ['mp3'], sticker: ['png'] }, max_size_mb: 200, fps: [24, 30], resolutions: [480, 720, 1080] } } as never)
  vi.mocked(editorApi.history).mockResolvedValue({ data: [] } as never)
  vi.mocked(editorApi.save).mockImplementation(async (_id, revision, document) => ({ data: { revision: revision + 1, document, updated_at: '' } }) as never)
})
function render(readOnly = false, attachTo?: HTMLElement) {
  const pinia = createPinia(); const auth = useAuthStore(pinia)
  if (readOnly) { auth.enabled = true; auth.memberships = [{ team_id: 1, role: 'viewer' }] as never }
  return mount(EditorWorkspace, { attachTo, props: { projectId: 9, chapterId: 450, filename: 'episode' }, global: { plugins: [pinia], stubs: { ResourceLibraryPicker: true, EditorPreview: { template: '<div></div>', methods: { seek() {} }, expose: ['seek'] } } } })
}
it.each(['dark', 'light'])('connects library, inspector and timeline while preserving source media (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const wrapper = render(); await flushPromises()
  expect(wrapper.findComponent(EditorLibrary).exists()).toBe(true)
  expect(wrapper.findComponent(EditorInspector).props('clip')).toMatchObject({ id: 'v1' })
  wrapper.findComponent(EditorTimeline).vm.$emit('select', 'v2'); await flushPromises()
  expect(wrapper.findComponent(EditorInspector).props('clip')).toMatchObject({ id: 'v2' })
  wrapper.findComponent(EditorTimeline).vm.$emit('remove'); await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(2)
  expect(wrapper.findComponent(EditorLibrary).props('media')).toHaveLength(3)
  wrapper.findComponent(EditorTimeline).vm.$emit('undo'); await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(3)
  wrapper.unmount()
})
it('flushes the exact edited revision before starting a render and restores persisted export history', async () => {
  vi.mocked(editorApi.export).mockResolvedValue({ data: { id: 4, task_id: 'task', status: 6, progress: 0, revision: 2 } } as never)
  const wrapper = render(); await flushPromises()
  wrapper.findComponent(EditorLibrary).vm.$emit('subtitle'); await flushPromises()
  wrapper.vm.openExport(); await flushPromises()
  await document.querySelector<HTMLButtonElement>('.editor-export-dialog .primary')?.click(); await flushPromises()
  expect(editorApi.save).toHaveBeenCalled()
  expect(editorApi.export).toHaveBeenCalledWith(450, 2)
  const doc = vi.mocked(editorApi.save).mock.calls[0]?.[2]
  expect(doc?.clips.some(c => c.type === 'subtitle')).toBe(true)
  wrapper.unmount()
})
it('does not expose edit or export permissions to viewers', async () => {
  const wrapper = render(true); await flushPromises()
  expect(wrapper.findComponent(EditorLibrary).props('readOnly')).toBe(true)
  expect(wrapper.findComponent(EditorTimeline).props('readOnly')).toBe(true)
  wrapper.findComponent(EditorLibrary).vm.$emit('subtitle'); await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(3)
  wrapper.vm.openExport(); await flushPromises()
  expect(document.querySelector<HTMLButtonElement>('.editor-export-dialog .primary')?.disabled).toBe(true)
  wrapper.unmount()
})

it('browses an imported source without inserting it until explicitly added', async () => {
  const wrapper = render(); await flushPromises()
  const source = { key: 'asset:9', source: { kind: 'asset' as const, id: 9 }, kind: 'video' as const, name: 'Extra', url: '/extra.mp4', duration: 2 }
  wrapper.findComponent(EditorLibrary).vm.$emit('select', source); await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(3)
  expect(wrapper.findComponent(EditorInspector).props('clip')).toBeNull()
  wrapper.findComponent(EditorLibrary).vm.$emit('add', source); await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(4)
  wrapper.unmount()
})

it('pins the media category for an upload batch while other add controls are used', async () => {
  const item = { key: 'asset:9', source: { kind: 'asset' as const, id: 9 }, kind: 'audio' as const, name: 'Music', url: '/music.wav', duration: 2 }
  let resolve!: (value: typeof item) => void
  vi.mocked(editorApi.upload).mockImplementationOnce(() => new Promise(r => { resolve = r })).mockResolvedValue(item)
  const wrapper = render(); await flushPromises()
  wrapper.findComponent(EditorLibrary).vm.$emit('upload', 'audio'); await flushPromises()
  const element = wrapper.findAll('input[type="file"]')[0]!
  Object.defineProperty(element.element, 'files', { configurable: true, value: [new File(['x'], 'a.mp3'), new File(['x'], 'b.mp3')] })
  await element.trigger('change'); await flushPromises()
  expect(wrapper.findComponent(EditorLibrary).props('busy')).toBe(true)
  wrapper.findComponent(EditorLibrary).vm.$emit('upload', 'sticker'); await flushPromises()
  resolve(item); await flushPromises()
  expect(vi.mocked(editorApi.upload).mock.calls.map(call => call[2])).toEqual(['audio', 'audio'])
  expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(3)
  wrapper.unmount()
})

it.each([
  ['dark', 'metaKey'],
  ['light', 'ctrlKey'],
] as const)('undoes and redoes keyboard edits while timeline controls retain focus (%s, %s)', async (theme, modifier) => {
  document.documentElement.dataset.appTheme = theme
  const wrapper = render(false, document.body); await flushPromises()
  try {
    const clip = wrapper.findAll('.editor-track-clip').at(-1)!
    await clip.trigger('click')
    await clip.trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.findComponent(EditorTimeline).props('document').clips[2].start).toBeCloseTo(4 + 1 / 24)
    const undo = wrapper.get('button[aria-label="撤销"]')
    expect(undo.attributes('disabled')).toBeUndefined()
    await undo.trigger('click')
    expect(wrapper.findComponent(EditorTimeline).props('document').clips[2].start).toBe(4)
    await wrapper.get('button[aria-label="重做"]').trigger('click')
    expect(wrapper.findComponent(EditorTimeline).props('document').clips[2].start).toBeCloseTo(4 + 1 / 24)

    for (const selector of ['.editor-track-clip.selected', '.editor-clip-handle.left', 'button[aria-label="撤销"]']) {
      await wrapper.get(selector).trigger('keydown', { key: 'z', [modifier]: true })
      expect(wrapper.findComponent(EditorTimeline).props('document').clips[2].start).toBe(4)
      await wrapper.get('.editor-track-clip.selected').trigger('keydown', { key: 'z', [modifier]: true, shiftKey: true })
      expect(wrapper.findComponent(EditorTimeline).props('document').clips[2].start).toBeCloseTo(4 + 1 / 24)
    }
    const input = wrapper.get('.editor-search input')
    const event = new KeyboardEvent('keydown', { key: 'z', [modifier]: true, bubbles: true, cancelable: true })
    input.element.dispatchEvent(event); await flushPromises()
    expect(event.defaultPrevented).toBe(false)
    expect(wrapper.findComponent(EditorTimeline).props('document').clips[2].start).toBeCloseTo(4 + 1 / 24)
  } finally { wrapper.unmount() }
})

it('keeps timeline undo shortcuts inactive for read-only viewers', async () => {
  const wrapper = render(true, document.body); await flushPromises()
  try {
    const event = new KeyboardEvent('keydown', { key: 'z', metaKey: true, bubbles: true, cancelable: true })
    wrapper.get('.editor-track-clip').element.dispatchEvent(event); await flushPromises()
    expect(event.defaultPrevented).toBe(false)
    expect(wrapper.findComponent(EditorTimeline).props('document')).toEqual(editorFixture().document)
    expect(wrapper.get('button[aria-label="撤销"]').attributes('disabled')).toBeDefined()
  } finally { wrapper.unmount() }
})

it('updates the preview when the timeline playhead seeks', async () => {
  const wrapper = render(); await flushPromises()
  const preview = wrapper.findComponent(EditorPreview)
  const seek = vi.spyOn(preview.vm, 'seek')
  wrapper.findComponent(EditorTimeline).vm.$emit('seek', 3.5); await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('time')).toBe(3.5)
  expect(seek).toHaveBeenCalledOnce()
  wrapper.unmount()
})
