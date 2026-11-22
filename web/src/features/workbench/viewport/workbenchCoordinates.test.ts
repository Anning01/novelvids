import { expect, it } from 'vitest'
import { initialCardViewport, screenPointForCenteredNode } from './workbenchCoordinates'

it('centers a node in canvas client coordinates', () => {
  expect(screenPointForCenteredNode(
    { left: 100, top: 40, width: 1200, height: 800 },
    { width: 360, height: 520 },
  )).toEqual({ x: 520, y: 180 })
})

it('centers newly added nodes using their size at the current zoom', () => {
  expect(screenPointForCenteredNode(
    { left: 100, top: 40, width: 1200, height: 800 },
    { width: 360, height: 520 },
    0.5,
  )).toEqual({ x: 610, y: 310 })
})

it('opens a narrow canvas on the first working card with its title and both sides visible', () => {
  const position = { x: 2080, y: 900 }
  const size = { width: 384, height: 683 }
  const view = initialCardViewport({ width: 400, height: 700 }, position, size, 120)
  expect(view.zoom).toBeGreaterThan(0.9)
  expect(view.x + position.x * view.zoom).toBe(20)
  expect(view.x + (position.x + size.width) * view.zoom).toBe(380)
  expect(view.y + position.y * view.zoom).toBe(56)
})

it('centers a short card between its title margin and the narrow canvas dock', () => {
  const view = initialCardViewport({ width: 400, height: 700 }, { x: 0, y: 0 }, { width: 360, height: 220 }, 120)
  expect(view).toEqual({ x: 20, y: 208, zoom: 1 })
})
