import { expect, it } from 'vitest'
import { routeWorkbenchWire, WireObstacles, type WireObstacle } from './edgeRouting'

const source: WireObstacle = { key: 'a', left: -208, right: 8, top: -80, bottom: 80 }
const target: WireObstacle = { key: 'b', left: 392, right: 608, top: -80, bottom: 80 }
const middle: WireObstacle = { key: 'block', left: 140, right: 240, top: -65, bottom: 65 }
function path(boxes: WireObstacle[]) {
  return routeWorkbenchWire({ x: 0, y: 0 }, { x: 400, y: 0 }, 'a', 'b', 'wire', new WireObstacles(boxes))
}

it('uses one cubic for clear runs and lets wires enter their own section', () => {
  const group = { ...middle, key: 'group', members: new Set(['a']) }
  expect(path([source, target, group])).toBe('M 0 0 C 200 0 200 0 400 0')
})
it('rounds the detour outside a blocking card and keeps the endpoints and path stable', () => {
  const routed = path([source, middle, target])
  expect(routed).toMatch(/^M 0 0 L .* Q .* L 400 0$/)
  const numbers = routed.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
  expect(numbers.some((n, i) => i % 2 === 1 && Math.abs(n) > 65)).toBe(true)
  expect(path([target, source, middle])).toBe(routed)
})
it('takes a return wire around the endpoint cards', () => {
  const routed = routeWorkbenchWire({ x: 600, y: 0 }, { x: -200, y: 0 }, 'b', 'a', 'return', new WireObstacles([source, target]))
  expect(routed).toContain(' Q ')
  expect(routed).toMatch(/ L -200 0$/)
})
