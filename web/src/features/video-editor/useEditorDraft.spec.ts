import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiRequestError } from '@/api'
import { editorApi } from './api'
import { useEditorDraft } from './useEditorDraft'
import type { EditDocument } from './types'
vi.mock('./api', () => ({ editorApi: { get: vi.fn(), save: vi.fn() } }))
const value: EditDocument = { version: 1, width: 1280, height: 720, fps: 24, clips: [] }
function render() {
  let state!: ReturnType<typeof useEditorDraft>
  const wrapper = mount(defineComponent({ setup() { state = useEditorDraft(() => 'user:team:project'); return () => h('div') } }))
  return { wrapper, state }
}
beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); vi.mocked(editorApi.get).mockResolvedValue({ data: { document: value, revision: 1, media: [], updated_at: '' } } as never) })
afterEach(() => vi.useRealTimers())

it('preserves local edits on optimistic conflicts and never automatically overwrites the server', async () => {
  vi.mocked(editorApi.save).mockRejectedValue(new ApiRequestError('Conflict', 409, 409))
  const { wrapper, state } = render(); await state.load(1)
  state.commit({ ...value, width: 1920, height: 1080 })
  expect(await state.save()).toBe(false)
  expect(state.conflict.value).toBe(true)
  expect(state.document.value?.width).toBe(1920)
  expect(await state.save()).toBe(false)
  expect(editorApi.save).toHaveBeenCalledTimes(1)
  expect(sessionStorage.length).toBe(1)
  wrapper.unmount()
})

it('serializes saves and retains edits made while the previous save was in flight', async () => {
  let resolve!: (value: never) => void
  vi.mocked(editorApi.save).mockImplementationOnce(() => new Promise(r => { resolve = r })).mockResolvedValue({ data: { revision: 3, document: { ...value, width: 1920 }, updated_at: '' } } as never)
  const { wrapper, state } = render(); await state.load(1)
  state.commit({ ...value, width: 1440 }); const pending = state.save()
  state.commit({ ...value, width: 1920 })
  resolve({ data: { revision: 2, document: { ...value, width: 1440 }, updated_at: '' } } as never)
  await pending; expect(state.dirty.value).toBe(true)
  await state.save(); expect(state.dirty.value).toBe(false)
  expect(vi.mocked(editorApi.save).mock.calls[1]?.[1]).toBe(2)
  wrapper.unmount()
})

it('ignores old chapter responses and keeps undo/redo isolated per chapter', async () => {
  let resolve!: (value: never) => void
  vi.mocked(editorApi.get).mockImplementationOnce(() => new Promise(r => { resolve = r }))
  const { wrapper, state } = render(); const first = state.load(1); await state.load(2)
  resolve({ data: { document: { ...value, width: 2000 }, revision: 4, media: [] } } as never); await first
  expect(state.document.value?.width).toBe(1280)
  state.commit({ ...value, width: 1440 }); state.undo(); expect(state.document.value?.width).toBe(1280)
  state.redo(); expect(state.document.value?.width).toBe(1440)
  await state.load(3); expect(state.undoStack.value).toHaveLength(0)
  wrapper.unmount(); await flushPromises()
})
