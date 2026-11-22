import { expect, it } from 'vitest'
import type { Point, WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import { buildWorkbenchAutoLayout, buildWorkbenchGroupedAutoLayout } from './workbenchAutoLayout'

const timestamp = '2026-07-25T00:00:00.000Z'

function makeNode(key: string, position: Point, kind: WorkbenchNode['kind'] = 'shot'): WorkbenchNode {
  return {
    id: Number(key.replace(/\D/g, '')) || -1,
    key,
    kind,
    backendKind: kind,
    title: key,
    position,
    size: { width: 360, height: 520 },
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: { layout_family: kind === 'shot' ? 'shot' : kind, ui: {} },
    createdAt: timestamp,
    updatedAt: timestamp,
  }
}

function makeShotNodes(count: number, size: { width: number; height: number }) {
  return Array.from({ length: count }, (_, index) => ({
    ...makeNode(`shot-${index + 1}`, { x: 0, y: index * 20 }),
    size,
    data: { layout_family: 'shot', shot_index: index + 1, ui: {} },
  }))
}

function makeSequenceEdges(nodes: WorkbenchNode[]): WorkbenchEdge[] {
  return nodes.slice(1).map((node, index) => ({
    id: index + 1,
    key: `sequence-${index}`,
    source: nodes[index]!.key,
    target: node.key,
    type: 'shot_sequence',
    backendType: 'shot_sequence',
    sourceHandle: null,
    targetHandle: null,
    orderIndex: index,
    config: null,
    createdAt: timestamp,
    updatedAt: timestamp,
  }))
}

function expectNoOverlaps(nodes: WorkbenchNode[], positions: Record<string, Point>) {
  for (let leftIndex = 0; leftIndex < nodes.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < nodes.length; rightIndex += 1) {
      const left = nodes[leftIndex]!
      const right = nodes[rightIndex]!
      const leftPosition = positions[left.key]!
      const rightPosition = positions[right.key]!
      const separated = leftPosition.x + left.size!.width <= rightPosition.x
        || rightPosition.x + right.size!.width <= leftPosition.x
        || leftPosition.y + left.size!.height <= rightPosition.y
        || rightPosition.y + right.size!.height <= leftPosition.y
      expect(separated, `${left.key} overlaps ${right.key}`).toBe(true)
    }
  }
}

it('wraps fifteen shots into bounded readable columns', () => {
  const nodes = makeShotNodes(15, { width: 360, height: 520 })
  const positions = buildWorkbenchAutoLayout(nodes, makeSequenceEdges(nodes), {
    maxColumnHeight: 1800,
  })
  const distinctX = new Set(nodes.map(node => positions[node.key]!.x))

  expect(distinctX.size).toBeGreaterThanOrEqual(5)
  expect(Math.max(...nodes.map(node => positions[node.key]!.y))).toBeLessThan(1800)
  expectNoOverlaps(nodes, positions)
})

it('does not move fixed nodes', () => {
  const nodes = [makeNode('fixed', { x: 740, y: 310 }), makeNode('free', { x: 0, y: 0 })]
  const positions = buildWorkbenchAutoLayout(nodes, [], {
    fixedNodeKeys: new Set(['fixed']),
  })

  expect(positions.fixed).toEqual({ x: 740, y: 310 })
})

it('centers mixed widths on the same column axis using measured card sizes', () => {
  const [portrait, landscape] = makeShotNodes(2, { width: 360, height: 520 })
  const positions = buildWorkbenchAutoLayout([portrait!, landscape!], [], {
    sizes: {
      [portrait!.key]: { width: 384, height: 684 },
      [landscape!.key]: { width: 544, height: 306 },
    },
  })
  const portraitPosition = positions[portrait!.key]!
  const landscapePosition = positions[landscape!.key]!
  expect(portraitPosition.x + 192).toEqual(landscapePosition.x + 272)
  expect(landscapePosition.y - portraitPosition.y - 684).toBeGreaterThanOrEqual(96)
})

it('keeps the chapter in place and wraps tall asset lanes alongside it', () => {
  const chapter = makeNode('chapter', { x: 200, y: 100 }, 'chapter')
  const assets = Array.from({ length: 5 }, (_, i) => makeNode(`asset-${i}`, { x: 0, y: i }, 'asset'))
  const positions = buildWorkbenchGroupedAutoLayout([chapter, ...assets], [], {
    sizes: { chapter: { width: 460, height: 220 } },
    columnGap: 100,
    maxColumnHeight: 1200,
  })
  expect(positions.chapter).toBeUndefined()
  expect(Math.min(...assets.map(n => positions[n.key]!.x))).toBe(760)
  expect(new Set(assets.map(n => positions[n.key]!.x)).size).toBe(3)
  expectNoOverlaps(assets, positions)
})
