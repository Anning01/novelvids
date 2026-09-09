import { createPinia, setActivePinia } from 'pinia'
import { expect, it, vi } from 'vitest'
import { api } from '@/api'
import { useWorkbenchStore } from './workbenchStore'
import type { Scene } from '@/types'

vi.mock('@/api', () => ({ api: { scene: vi.fn(), asset: vi.fn() }, mediaUrl: (v: string) => v, persistedMediaRef: () => '' }))

const scene = (prompt: string): Scene => ({ id: 2, chapter_id: 1, sequence: 1, prompt, duration: 6,
  metadata: {}, created_at: '', updated_at: '' })

it('keeps a selected canvas node draft while updating the backend snapshot', async () => {
  setActivePinia(createPinia())
  const store = useWorkbenchStore()
  store.chapterId = 1
  store.scenes = [scene('旧后端提示词')]
  store.nodes = [{ id: 2, key: 'scene-2', kind: 'shot', backendKind: 'shot', title: '视频 01', position: { x: 0, y: 0 },
    size: null, zIndex: 1, activeVersionId: null, status: 'ready', data: { scene: scene('正在编辑的本地草稿') }, createdAt: '', updatedAt: '' }]
  store.selectedNodeKeys = ['scene-2']
  store.nodes[0]!.data.prompt_dirty = true
  vi.mocked(api.scene).mockResolvedValue({ code: 0, message: '', data: scene('助手已保存的新提示词') })
  const conflicts = await store.refreshAgentPrompts([{ kind: 'scene', target_id: 2 }])
  expect(store.scenes[0]?.prompt).toBe('助手已保存的新提示词')
  expect((store.nodes[0]?.data.scene as Scene).prompt).toBe('正在编辑的本地草稿')
  expect(conflicts).toEqual(['视频 01'])
})

it('refreshes an idle canvas node from the authoritative API', async () => {
  setActivePinia(createPinia())
  const store = useWorkbenchStore()
  store.chapterId = 1
  store.scenes = [scene('旧提示词')]
  store.nodes = [{ id: 2, key: 'scene-2', kind: 'shot', backendKind: 'shot', title: '视频 01', position: { x: 0, y: 0 },
    size: null, zIndex: 1, activeVersionId: null, status: 'ready', data: { scene: scene('旧提示词') }, createdAt: '', updatedAt: '' }]
  vi.mocked(api.scene).mockResolvedValue({ code: 0, message: '', data: scene('新提示词') })
  expect(await store.refreshAgentPrompts([{ kind: 'scene', target_id: 2 }])).toEqual([])
  expect((store.nodes[0]?.data.scene as Scene).prompt).toBe('新提示词')
})
