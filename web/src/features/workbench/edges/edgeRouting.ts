import type { Point } from '../types/workbenchTypes'

export interface WireObstacle {
  key: string
  left: number
  right: number
  top: number
  bottom: number
  members?: ReadonlySet<string>
}

const CHANNEL_CLEARANCE = 16
const CORNER_RADIUS = 10
const DIRECT_CURVE_STEPS = 12
const MAX_LOCAL_CHANNELS = 16

/** Index world-space rectangles once, shared by all wires; zoom does not change them. */
export class WireObstacles {
  private readonly sorted: WireObstacle[]
  private readonly rightmost: number[] = []

  constructor(rectangles: WireObstacle[]) {
    this.sorted = [...rectangles].sort((a, b) => a.left - b.left)
    let right = -Infinity
    for (const box of this.sorted) {
      right = Math.max(right, box.right)
      this.rightmost.push(right)
    }
  }

  between(left: number, right: number, source: string, target: string) {
    let low = 0, high = this.sorted.length
    while (low < high) {
      const mid = (low + high) >>> 1
      if (this.rightmost[mid]! < left) low = mid + 1
      else high = mid
    }
    const boxes: WireObstacle[] = []
    for (let i = low; i < this.sorted.length; i++) {
      const box = this.sorted[i]!
      if (box.left > right) break
      if (box.right >= left && !box.members?.has(source) && !box.members?.has(target)) boxes.push(box)
    }
    return boxes
  }
}

function intersects(a: Point, b: Point, box: WireObstacle) {
  return Math.max(a.x, b.x) >= box.left && Math.min(a.x, b.x) <= box.right
    && Math.max(a.y, b.y) >= box.top && Math.min(a.y, b.y) <= box.bottom
}

function roundedPath(points: Point[]) {
  const turns: Point[] = []
  for (const p of points) {
    const b = turns.at(-1), a = turns.at(-2)
    if (b && p.x === b.x && p.y === b.y) continue
    if (a && b && ((a.x === b.x && b.x === p.x) || (a.y === b.y && b.y === p.y))) turns.pop()
    turns.push(p)
  }
  const first = turns[0]!, last = turns.at(-1)!
  let path = `M ${first.x} ${first.y}`
  for (let i = 1; i < turns.length - 1; i++) {
    const a = turns[i - 1]!, b = turns[i]!, c = turns[i + 1]!
    const radius = Math.min(CORNER_RADIUS, Math.hypot(b.x - a.x, b.y - a.y) / 2, Math.hypot(c.x - b.x, c.y - b.y) / 2)
    path += ` L ${b.x - Math.sign(b.x - a.x) * radius} ${b.y - Math.sign(b.y - a.y) * radius}`
    path += ` Q ${b.x} ${b.y} ${b.x + Math.sign(c.x - b.x) * radius} ${b.y + Math.sign(c.y - b.y) * radius}`
  }
  return path + ` L ${last.x} ${last.y}`
}

/** All workbench ports exit right and enter left. Preserve exact live handle coordinates. */
export function routeWorkbenchWire(start: Point, end: Point, source: string, target: string, edgeKey: string, index: WireObstacles) {
  // Related detours share the terminal stubs but do not all trace the very same rail.
  let hash = 0
  for (const char of edgeKey) hash = (hash * 31 + char.charCodeAt(0)) | 0
  const channel = CHANNEL_CLEARANCE + (Math.abs(hash) % 4) * 4
  const dx = end.x - start.x, dy = end.y - start.y
  const lead = dx > 0 ? Math.min(channel + 12, dx / 3) : channel + 12
  const exit = { x: start.x + lead, y: start.y }, entry = { x: end.x - lead, y: end.y }
  const boxes = index.between(Math.min(start.x, entry.x), Math.max(end.x, exit.x), source, target)
  if (dx > 0) {
    const blockers = boxes.filter(box => box.key !== source && box.key !== target && intersects(start, end, box))
    let previous = start, blocked = false
    // With horizontal tangents both coordinates are monotone. Each interval's
    // bounding rectangle contains the entire piece of curve, including its extrema.
    for (let i = 1; blockers.length && !blocked && i <= DIRECT_CURVE_STEPS; i++) {
      const t = i / DIRECT_CURVE_STEPS
      const p = { x: start.x + dx * t * (1.5 - 1.5 * t + t * t), y: start.y + dy * t * t * (3 - 2 * t) }
      blocked = blockers.some(box => intersects(previous, p, box))
      previous = p
    }
    if (!blocked) {
      const middle = (start.x + end.x) / 2
      return `M ${start.x} ${start.y} C ${middle} ${start.y} ${middle} ${end.y} ${end.x} ${end.y}`
    }
  }

  // Try a vertical aisle first when a forward curve clips a card near one endpoint.
  if (dx > 0 && dy !== 0) {
    const midX = (exit.x + entry.x) / 2
    const aisles = new Set([midX])
    for (const box of boxes) {
      for (const x of [box.left - channel, box.right + channel])
        if (x >= exit.x && x <= entry.x) aisles.add(x)
    }
    for (const x of [...aisles].sort((a, b) => Math.abs(a - midX) - Math.abs(b - midX) || a - b).slice(0, MAX_LOCAL_CHANNELS)) {
      const a = { x, y: start.y }, b = { x, y: end.y }
      if (!boxes.some(box => (box.key !== source && intersects(start, a, box)) || intersects(a, b, box)
        || (box.key !== target && intersects(b, end, box)))) return roundedPath([start, a, b, end])
    }
  }

  const middleY = (start.y + end.y) / 2
  const rows = new Set([middleY, start.y, end.y, Math.min(start.y, end.y) - channel, Math.max(start.y, end.y) + channel])
  for (const box of boxes) { rows.add(box.top - channel); rows.add(box.bottom + channel) }
  const sorted = [...rows].sort((a, b) => Math.abs(a - middleY) - Math.abs(b - middleY) || a - b)
  const channels = sorted.slice(0, MAX_LOCAL_CHANNELS)
  channels.push(Math.min(...rows), Math.max(...rows))
  let best = [start, exit, entry, end], fewestHits = Infinity
  for (const y of channels) {
    const bend1 = { x: exit.x, y }, bend2 = { x: entry.x, y }
    let hits = 0
    for (const box of boxes) {
      if (intersects(exit, bend1, box) || intersects(bend1, bend2, box) || intersects(bend2, entry, box)
        || (box.key !== source && intersects(start, exit, box)) || (box.key !== target && intersects(entry, end, box))) hits++
    }
    if (hits < fewestHits) { best = [start, exit, bend1, bend2, entry, end]; fewestHits = hits }
    if (!hits) break
  }
  return roundedPath(best)
}
