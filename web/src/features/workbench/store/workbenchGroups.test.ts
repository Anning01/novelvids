import { createPinia, setActivePinia } from 'pinia'
import { expect, it } from 'vitest'
import { commonMarkerColor } from '../graph/nodeAppearance'
import type { WorkbenchNode } from '../types/workbenchTypes'
import { useWorkbenchStore } from './workbenchStore'

it('keeps group membership, name and colors across undo, redo and reloading an existing layout', () => {
  localStorage.clear()
  setActivePinia(createPinia())
  const store = useWorkbenchStore()
  const chapter: WorkbenchNode = {
    id: 7, key: 'chapter', kind: 'chapter', backendKind: 'chapter', title: 'chapter',
    position: { x: 10, y: 10 }, size: null, zIndex: 1, activeVersionId: null,
    status: 'ready', data: { ui: { pinned: true } }, createdAt: '', updatedAt: '',
  }
  store.novelId = 1
  store.chapterId = 7
  store.nodes.push(chapter)
  const note = store.addNote({ x: 200, y: 20 })
  const keys = [chapter.key, note.key]
  store.setNodeColors(keys, '#70a98a')
  expect(commonMarkerColor(store.nodes)).toBe('#70a98a')
  expect(store.nodeByKey(chapter.key)?.data.ui?.pinned).toBe(true)
  store.undo()
  expect(commonMarkerColor(store.nodes)).toBe('')
  store.redo()
  const group = store.addSection(keys, { x: 0, y: 0 }, { width: 600, height: 300 }, '#70a98a')
  store.renameSection(group.key, '  人物素材  ')
  store.renameSection(group.key, '  ')
  store.setNodeColors([group.key], '#d584b8')
  store.setNodeColors([chapter.key], '')
  expect(store.nodeByKey(chapter.key)?.data.ui?.pinned).toBe(true)

  setActivePinia(createPinia())
  const restored = useWorkbenchStore()
  restored.novelId = 1
  restored.chapterId = 7
  restored.nodes.push({ ...chapter, data: {} })
  restored.loadSavedLayout()
  expect(restored.nodeByKey(group.key)).toMatchObject({ title: '人物素材', data: { color: '#d584b8', node_keys: keys } })
  expect(restored.nodeByKey(note.key)?.data.color).toBe('#70a98a')
  expect(restored.nodeByKey(chapter.key)?.data.ui).toMatchObject({ color: '', pinned: true })
})
