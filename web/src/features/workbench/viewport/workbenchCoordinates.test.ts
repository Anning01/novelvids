import { expect, it } from 'vitest'
import { screenPointForCenteredNode } from './workbenchCoordinates'

it('centers a node in canvas client coordinates', () => {
  expect(screenPointForCenteredNode(
    { left: 100, top: 40, width: 1200, height: 800 },
    { width: 360, height: 520 },
  )).toEqual({ x: 520, y: 180 })
})
