import { expect, it } from 'vitest'
import type { WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import { parseWorkbenchState } from './workbenchPersistence'

const timestamp = '2026-07-25T00:00:00.000Z'
const note = {
  id: -1,
  key: 'note-1',
  kind: 'note',
  backendKind: 'note',
  title: '便签',
  position: { x: 20, y: 30 },
  size: { width: 320, height: 220 },
  zIndex: 1,
  activeVersionId: null,
  status: 'ready',
  data: { content: '内容', color: '#8d793d', ui: {} },
  createdAt: timestamp,
  updatedAt: timestamp,
} satisfies WorkbenchNode
const mediaEdge = {
  id: -2,
  key: 'media-edge-1',
  source: 'note-1',
  target: 'shot-1',
  type: 'asset_reference',
  backendType: 'asset_reference',
  sourceHandle: null,
  targetHandle: null,
  orderIndex: 0,
  config: null,
  createdAt: timestamp,
  updatedAt: timestamp,
} satisfies WorkbenchEdge

it('migrates layout v1 manual nodes and media edges', () => {
  const parsed = parseWorkbenchState(JSON.stringify({
    viewport: { x: 2, y: 3, zoom: 1 },
    manualNodes: [note],
    mediaEdges: [mediaEdge],
  }))

  expect(parsed?.version).toBe(2)
  expect(parsed?.manualNodes[0]?.key).toBe('note-1')
  expect(parsed?.manualEdges[0]?.key).toBe('media-edge-1')
})
