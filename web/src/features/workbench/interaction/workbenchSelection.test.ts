import type { NodeChange } from '@vue-flow/core'
import { describe, expect, it } from 'vitest'
import { applyNodeSelectionChanges, isInteractiveSelectionTarget, selectionAfterNodeClick, selectionGestureMoved } from './workbenchSelection'

describe('applyNodeSelectionChanges', () => {
  const valid = new Set(['a', 'b', 'c'])

  it('applies selects and deselects from one event batch', () => {
    const changes: NodeChange[] = [
      { id: 'a', type: 'select', selected: false },
      { id: 'b', type: 'select', selected: true },
    ]

    expect(applyNodeSelectionChanges(['a'], changes, valid)).toEqual(['b'])
  })

  it('keeps native multi-selection order and drops stale keys', () => {
    const changes: NodeChange[] = [
      { id: 'c', type: 'select', selected: true },
    ]

    expect(applyNodeSelectionChanges(['a', 'missing'], changes, valid)).toEqual(['a', 'c'])
  })

  it('derives authoritative click selection from the pre-pointerdown snapshot', () => {
    expect(selectionAfterNodeClick([], 'a', false)).toEqual(['a'])
    expect(selectionAfterNodeClick(['a'], 'b', false)).toEqual(['b'])
    expect(selectionAfterNodeClick(['a'], 'b', true)).toEqual(['a', 'b'])
    expect(selectionAfterNodeClick(['a', 'b'], 'b', true)).toEqual(['a'])
  })

  it('distinguishes a blank click from a lasso gesture', () => {
    expect(selectionGestureMoved({ x: 20, y: 20 }, { x: 22, y: 22 })).toBe(false)
    expect(selectionGestureMoved({ x: 20, y: 20 }, { x: 24, y: 20 })).toBe(true)
  })

  it('does not treat form-control clicks as node-selection clicks', () => {
    const button = document.createElement('button')
    const option = document.createElement('span')
    option.setAttribute('role', 'option')
    const plain = document.createElement('div')

    expect(isInteractiveSelectionTarget(button)).toBe(true)
    expect(isInteractiveSelectionTarget(option)).toBe(true)
    expect(isInteractiveSelectionTarget(plain)).toBe(false)
  })
})
