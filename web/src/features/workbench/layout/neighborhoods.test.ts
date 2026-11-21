import { expect, it } from 'vitest'
import type { WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import { buildWorkbenchGroupedAutoLayout } from './workbenchAutoLayout'
import { near } from './neighborhoods'

function node(key: string, kind: WorkbenchNode['kind'], x: number, y: number, width = 200, height = 120): WorkbenchNode {
  return { id: 1, key, kind, backendKind: kind, title: key, position: { x, y }, size: { width, height },
    data: {}, zIndex: 1, activeVersionId: null, status: 'ready', createdAt: '', updatedAt: '' }
}
function wire(source: string, target: string): WorkbenchEdge {
  return { id: 1, key: source + target, source, target, type: 'asset_reference', backendType: 'asset_reference',
    sourceHandle: null, targetHandle: null, orderIndex: 0, config: null, createdAt: '', updatedAt: '' }
}

it('preserves the exact bounds and contents of old groups and attaches external cards on the correct sides', () => {
  const group = node('group', 'section', -1800, 900, 800, 460)
  group.data.node_keys = ['member', 'missing']
  const member = node('member', 'shot', -1540, 1130)
  const note = node('note', 'note', -300, 4000)
  const pinned = node('pinned', 'asset', 6000, -4000)
  const input = node('input', 'asset', 4000, 5000)
  const output = node('output', 'video_result', -6000, -4000)
  const nodes = [input, group, output, member, note, pinned]
  const edges = [wire(input.key, member.key), wire(member.key, output.key)]
  const options = { fixedNodeKeys: new Set([pinned.key]), columnGap: 100, rowGap: 80 }
  const before = JSON.stringify(nodes)
  const layout = buildWorkbenchGroupedAutoLayout(nodes, edges, options)
  expect(JSON.stringify(nodes)).toBe(before)
  expect(Object.keys(layout).sort()).toEqual(['input', 'output'])
  expect(layout.input).toEqual({ x: -2100, y: 1130 })
  expect(layout.output).toEqual({ x: -900, y: 1130 })
  expect(buildWorkbenchGroupedAutoLayout(nodes.map(n => ({ ...n, position: layout[n.key] ?? n.position })), edges, options)).toEqual(layout)
})

it('keeps independent workflows near their original locations and avoids reserved space even without any edges to it', () => {
  const nodes = [node('a', 'asset', 50, 100), node('b', 'shot', 520, 70),
    node('c', 'asset', 5100, 5400), node('d', 'shot', 4650, 5450),
    node('border', 'section', 4750, 5220, 470, 420), node('note', 'note', 4500, 5650)]
  const edges = [wire('a', 'b'), wire('c', 'd')]
  const result = buildWorkbenchGroupedAutoLayout(nodes, edges, { columnGap: 100 })
  expect(result.a!.x).toBeLessThan(result.b!.x)
  expect(result.c!.x).toBeLessThan(result.d!.x)
  expect(Math.hypot(result.c!.x - 5100, result.c!.y - 5400)).toBeLessThan(1000)
  const boxes = nodes.map(n => ({ ...(result[n.key] ?? n.position), ...n.size! }))
  for (const [i, a] of boxes.entries())
    for (const b of boxes.slice(i + 1)) expect(near(a, b, 0, 0)).toBe(false)
  const placed = nodes.map(n => ({ ...n, position: result[n.key] ?? n.position }))
  expect(buildWorkbenchGroupedAutoLayout(placed, edges, { columnGap: 100 })).toEqual(result)
})

it('aligns partial result columns with the shot they belong to and retains shot order', () => {
  const a = node('origin', 'asset', 0, 0), first = node('shot1', 'shot', 500, 500), second = node('shot2', 'shot', 500, 0)
  first.data.shot_index = 1; second.data.shot_index = 2
  const result = buildWorkbenchGroupedAutoLayout([a, first, second, node('result', 'video_result', 700, 400)],
    [wire('origin', 'shot1'), wire('origin', 'shot2'), wire('shot2', 'result')])
  expect(result.shot1!.y).toBeLessThan(result.shot2!.y)
  expect(result.result!.y).toBe(result.shot2!.y)
})

it('untangles crossed references without reversing the shots', () => {
  const a = node('a', 'asset', 0, 0), b = node('b', 'asset', 0, 500)
  const one = node('one', 'shot', 600, 0), two = node('two', 'shot', 600, 500)
  one.data.shot_index = 1; two.data.shot_index = 2
  const positions = buildWorkbenchGroupedAutoLayout([a, b, one, two], [wire('a', 'two'), wire('b', 'one'), wire('a', 'one')])
  expect(positions.b!.y).toBeLessThan(positions.a!.y)
  expect(positions.one!.y).toBeLessThan(positions.two!.y)
})

it('leaves an entirely protected canvas untouched, including a pinned card outside any group', () => {
  const group = node('g', 'section', 44, 100), member = node('m', 'asset', 60, 170)
  group.data.node_keys = [member.key]
  const pinned = node('p', 'shot', -40, 0), locked = node('locked', 'video_result', 720, 200)
  pinned.zIndex = 1_000_000; locked.data.ui = { locked: true }
  expect(buildWorkbenchGroupedAutoLayout([group, member, pinned, locked])).toEqual({})
})

it('keeps linked cards one compact gutter apart while leaving room above the next row', () => {
  const first = node('a', 'asset', 0, 0), second = node('b', 'asset', 0, 800)
  const shot = node('shot', 'shot', 1600, 400)
  const placed = buildWorkbenchGroupedAutoLayout([first, second, shot], [wire('a', 'shot'), wire('b', 'shot')])
  expect(placed.shot!.x - placed.a!.x - first.size!.width).toBe(72)
  expect(Math.abs(placed.b!.y - placed.a!.y) - first.size!.height).toBe(96)
})
