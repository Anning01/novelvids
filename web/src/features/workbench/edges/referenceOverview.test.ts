import { expect, it } from 'vitest'
import { detailOnlyReferences } from './referenceOverview'
import type { WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'

const card = (key: string, x: number, y: number) => ({ key, position: { x, y }, size: { width: 200, height: 100 } } as WorkbenchNode)
const wire = (source: string, target: string, type = 'asset_reference') => ({ key: source + target, source, target, type } as WorkbenchEdge)

it('keeps nearby reference curves at crowded outputs and leaves sparse links and sequence edges visible', () => {
  const targets = [3, 0, 2, 1, 4].map(i => card('shot' + i, 300, i * 200))
  const nodes = [card('asset', 0, 0), ...targets]
  const edges = targets.map(node => wire('asset', node.key))
  expect(detailOnlyReferences(nodes, [...edges, wire('shot0', 'shot4', 'shot_sequence')]))
    .toEqual(new Set(['assetshot2', 'assetshot3', 'assetshot4']))
  expect(detailOnlyReferences(nodes, edges.slice(0, 3)).size).toBe(0)
})

it('limits fan-in independently of fan-out and ranks again after a card moves', () => {
  const nodes = [0, 1, 2, 3].map(i => card('a' + i, 0, i * 200))
  const edges = nodes.map(node => wire(node.key, 'shot'))
  expect(detailOnlyReferences([...nodes, card('shot', 300, 600)], edges)).toEqual(new Set(['a0shot', 'a1shot']))
  expect(detailOnlyReferences([...nodes, card('shot', 300, 0)], edges)).toEqual(new Set(['a2shot', 'a3shot']))
})
