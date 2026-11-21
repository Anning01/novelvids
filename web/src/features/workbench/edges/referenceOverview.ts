import type { WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'

/** In overview, crowded ports expose their two shortest routes. Inspection always uses the full graph. */
export function detailOnlyReferences(nodes: WorkbenchNode[], edges: WorkbenchEdge[]) {
  const byKey = new Map(nodes.map(node => [node.key, node]))
  const inputs = new Map<string, number>(), outputs = new Map<string, number>()
  const routes = edges.flatMap(edge => {
    if (edge.type !== 'asset_reference') return []
    const source = byKey.get(edge.source), target = byKey.get(edge.target)
    if (!source || !target) return []
    const dx = target.position.x - source.position.x - (source.size?.width ?? 360)
    const dy = target.position.y + (target.size?.height ?? 280) / 2
      - source.position.y - (source.size?.height ?? 280) / 2
    inputs.set(target.key, (inputs.get(target.key) ?? 0) + 1)
    outputs.set(source.key, (outputs.get(source.key) ?? 0) + 1)
    return [{ edge, distance: dx * dx + dy * dy }]
  })
  const detail = new Set<string>()
  const shownInputs = new Map<string, number>(), shownOutputs = new Map<string, number>()
  for (const { edge } of routes.sort((a, b) => a.distance - b.distance || a.edge.key.localeCompare(b.edge.key))) {
    const usedIn = shownInputs.get(edge.target) ?? 0, usedOut = shownOutputs.get(edge.source) ?? 0
    if ((inputs.get(edge.target)! > 3 && usedIn >= 2) || (outputs.get(edge.source)! > 3 && usedOut >= 2)) {
      detail.add(edge.key)
    } else {
      shownInputs.set(edge.target, usedIn + 1)
      shownOutputs.set(edge.source, usedOut + 1)
    }
  }
  return detail
}
