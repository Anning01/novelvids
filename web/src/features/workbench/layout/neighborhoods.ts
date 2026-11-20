import type { NodeSize, Point, WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'

const keyOrder = new Intl.Collator('en', { numeric: true }).compare

export type LayoutBox = Point & NodeSize

export function median(values: number[]) {
  const sorted = values.sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle]! : (sorted[middle - 1]! + sorted[middle]!) / 2
}

export function boundsOf(boxes: LayoutBox[]): LayoutBox {
  const x = Math.min(...boxes.map(box => box.x)), y = Math.min(...boxes.map(box => box.y))
  return { x, y, width: Math.max(...boxes.map(box => box.x + box.width)) - x,
    height: Math.max(...boxes.map(box => box.y + box.height)) - y }
}

export function near(a: LayoutBox, b: LayoutBox, gapX: number, gapY: number) {
  return a.x < b.x + b.width + gapX && b.x < a.x + a.width + gapX
    && a.y < b.y + b.height + gapY && b.y < a.y + a.height + gapY
}

/** Search the boundaries of occupied rectangles, keeping the preferred position when it fits. */
export function nearestFreeBox(desired: LayoutBox, occupied: LayoutBox[], gapX: number, gapY: number) {
  const blockers = occupied.filter(box => near(desired, box, gapX, gapY))
  if (!blockers.length) return desired
  const candidates = new Set([desired.x])
  for (const box of blockers) {
    candidates.add(box.x - desired.width - gapX)
    candidates.add(box.x + box.width + gapX)
  }
  let best = desired, bestDistance = Infinity
  for (const x of candidates) {
    if ((x - desired.x) ** 2 >= bestDistance) continue
    const intervals = occupied.filter(box => x < box.x + box.width + gapX && x + desired.width + gapX > box.x)
      .map(box => ({ top: box.y - desired.height - gapY, bottom: box.y + box.height + gapY }))
      .sort((a, b) => a.top - b.top)
    let y = desired.y
    for (let i = 0; i < intervals.length; i++) {
      const { top } = intervals[i]!
      let { bottom } = intervals[i]!
      while (i + 1 < intervals.length && intervals[i + 1]!.top < bottom) bottom = Math.max(bottom, intervals[++i]!.bottom)
      if (top < y && y < bottom) {
        y = y - top < bottom - y ? top : bottom
        break
      }
    }
    const distance = (x - desired.x) ** 2 + (y - desired.y) ** 2
    if (distance < bestDistance) { best = { ...desired, x, y }; bestDistance = distance }
  }
  return best
}

export interface Neighborhood {
  nodes: WorkbenchNode[]
  edges: WorkbenchEdge[]
  anchors: WorkbenchEdge[]
}

/** Follow actual connections. Only orphan cards of the same lane are gathered by proximity. */
export function neighborhoods(nodes: WorkbenchNode[], edges: WorkbenchEdge[], boxes: Map<string, LayoutBox>,
  laneOf: (node: WorkbenchNode) => string, gapX: number, gapY: number) {
  const leaders = new Map(nodes.map(node => [node.key, node.key]))
  function leader(key: string): string {
    let root = key
    while (leaders.get(root) !== root) root = leaders.get(root)!
    while (key !== root) {
      const parent = leaders.get(key)!
      leaders.set(key, root)
      key = parent
    }
    return root
  }
  function join(a: string, b: string) {
    const root = leader(a), other = leader(b)
    if (root !== other) leaders.set(other, root)
  }
  const attached = new Set<string>()
  for (const edge of edges) {
    if (edge.source === edge.target || !boxes.has(edge.source) || !boxes.has(edge.target)) continue
    attached.add(edge.source); attached.add(edge.target)
    if (leaders.has(edge.source) && leaders.has(edge.target)) join(edge.source, edge.target)
  }
  const loose = nodes.filter(node => !attached.has(node.key)).sort((a, b) => a.position.x - b.position.x)
  for (const [i, node] of loose.entries()) {
    const box = boxes.get(node.key)!
    for (let j = i + 1; j < loose.length; j++) {
      const other = loose[j]!
      if (other.position.x > box.x + box.width + gapX) break
      if (laneOf(node) === laneOf(other) && near(box, boxes.get(other.key)!, gapX / 2, gapY / 2)) {
        join(node.key, other.key)
      }
    }
  }
  const groups = new Map<string, Neighborhood>()
  const owners = new Map<string, Neighborhood>()
  for (const node of [...nodes].sort((a, b) => keyOrder(a.key, b.key))) {
    const id = leader(node.key)
    const group = groups.get(id) ?? { nodes: [], edges: [], anchors: [] }
    group.nodes.push(node)
    groups.set(id, group)
    owners.set(node.key, group)
  }
  for (const edge of edges) {
    if (edge.source === edge.target || !boxes.has(edge.source) || !boxes.has(edge.target)) continue
    const source = owners.get(edge.source), target = owners.get(edge.target)
    if (source && source === target) source.edges.push(edge)
    else (source ?? target)?.anchors.push(edge)
  }
  // Attached workflows get first choice of the space next to their fixed endpoints.
  return [...groups.values()].sort((a, b) => Number(Boolean(b.anchors.length)) - Number(Boolean(a.anchors.length)))
}
