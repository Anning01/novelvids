import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it } from 'vitest'
import { useWorkbenchStore } from '@/features/workbench/store/workbenchStore'
import type { VideoResource } from './types'

beforeEach(() => { setActivePinia(createPinia()); localStorage.clear() })
const resource = { id: 7, filename: 'motion.mp4', name: '动作参考', url: 'https://cdn.invalid/motion.mp4', storage_ref: 'uploads/1/motion.mp4', content_type: 'video/mp4', width: 1280, height: 720, duration: 4 } as VideoResource
it('persists resource identity separately from its display URL and emits a video reference only for linked nodes', () => {
  const store = useWorkbenchStore()
  store.novelId = 1; store.chapterId = 2
  const item = store.addLibraryVideo(resource)
  expect(item.kind).toBe('video_media')
  expect(item.data).toMatchObject({ library_resource_id: 7, url: resource.url, storage_ref: resource.storage_ref })
  expect(store.libraryVideoReferences(3)).toEqual([])
  store.edges.push({ key: 'ref', id: 1, type: 'asset_reference', source: item.key, target: 'shot-3', orderIndex: 0, config: null } as typeof store.edges[number])
  expect(store.libraryVideoReferences(3)).toEqual([{ type: 'video', url: resource.storage_ref, library_resource_id: 7, mention_name: '动作参考', name: '动作参考', duration: 4 }])
  const persisted = JSON.parse(localStorage.getItem(store.layoutKey()) || '{}')
  expect(persisted.manualNodes[0].data.library_resource_id).toBe(7)
  store.edges[0]!.config = { inputMode: 'prompt_injection' }
  expect(store.libraryVideoReferences(3)).toEqual([])
})

it('assigns unique node IDs when selecting a batch in the same millisecond', () => {
  const store = useWorkbenchStore()
  const first = store.addLibraryVideo(resource)
  const second = store.addLibraryVideo({ ...resource, id: 8 })
  expect(second.key).not.toBe(first.key)
  expect(second.id).not.toBe(first.id)
})

it('keeps references selected in storyboard when generating from the canvas', () => {
  const store = useWorkbenchStore()
  store.scenes = [{ id: 3, sequence: 1, created_at: '', updated_at: '', metadata: { video_reference_media: [{ type: 'video', url: '/media/a.mp4', library_resource_id: 7, mention_url: 'uploads/1/a.mp4', duration: 4 }] } } as typeof store.scenes[number]]
  expect(store.libraryVideoReferences(3)).toMatchObject([{ library_resource_id: 7, mention_url: 'uploads/1/a.mp4', duration: 4 }])
})

it('keeps URL mentions from storyboard and name mentions from canvas for the same resource', () => {
  const store = useWorkbenchStore()
  store.scenes = [{ id: 3, sequence: 1, created_at: '', updated_at: '', metadata: { video_reference_media: [{ type: 'video', url: resource.url, library_resource_id: 7, mention_url: resource.storage_ref }] } }]
  const item = store.addLibraryVideo(resource)
  store.edges.push({ key: 'ref', id: 1, type: 'asset_reference', source: item.key, target: 'shot-3', orderIndex: 0, config: null } as typeof store.edges[number])
  expect(store.libraryVideoReferences(3)).toHaveLength(1)
  expect(store.libraryVideoReferences(3)[0]).toMatchObject({ mention_name: '动作参考', mention_url: resource.storage_ref })
})
