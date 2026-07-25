import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { useWorkbenchStore } from './workbenchStore'

vi.mock('@/api', () => ({
  api: { createScene: vi.fn() },
  sleep: vi.fn(),
}))

const createSceneMock = vi.mocked(api.createScene)
let store: ReturnType<typeof useWorkbenchStore>

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkbenchStore()
  store.chapterId = 2162
})

it('does not leave a shot when createScene rejects', async () => {
  createSceneMock.mockRejectedValueOnce(new Error('network'))

  await expect(store.addShot({ x: 20, y: 30 })).rejects.toThrow('network')
  expect(store.nodes.some(node => node.kind === 'shot')).toBe(false)
})

it('deletes an explicit note key and restores selection through undo and redo', async () => {
  vi.spyOn(Date, 'now')
    .mockReturnValueOnce(1001)
    .mockReturnValueOnce(1002)
  const first = store.addNote({ x: 20, y: 30 })
  const second = store.addNote({ x: 80, y: 90 })
  store.selectNode(second.key)

  await expect(store.deleteNodeKeys([first.key])).resolves.toBe(1)
  expect(store.nodeByKey(first.key)).toBeUndefined()
  expect(store.selectedNodeKeys).toEqual([second.key])

  expect(store.undo()).toBe(true)
  expect(store.nodeByKey(first.key)).toBeTruthy()
  expect(store.selectedNodeKeys).toEqual([second.key])

  expect(store.redo()).toBe(true)
  expect(store.nodeByKey(first.key)).toBeUndefined()
})

it('copies and pastes a note with the copied content selected', async () => {
  vi.spyOn(Date, 'now')
    .mockReturnValueOnce(2001)
    .mockReturnValueOnce(2002)
  const original = store.addNote({ x: 20, y: 30 })
  store.updateManualNodeData(original.key, { content: '复制内容' })
  store.copySelection()

  await store.paste()

  const notes = store.nodes.filter(node => node.kind === 'note')
  expect(notes).toHaveLength(2)
  expect(notes[1]?.data.content).toBe('复制内容')
  expect(store.selectedNodeKeys).toEqual([notes[1]!.key])
})
