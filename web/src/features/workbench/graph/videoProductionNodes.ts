import type { WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'

function isVideoResultBinding(edge: WorkbenchEdge) {
  return edge.type === 'output_binding'
}

export function videoResultOwners(
  nodes: readonly WorkbenchNode[],
  edges: readonly WorkbenchEdge[],
) {
  const productionKeys = new Set(nodes.filter(node => node.kind === 'shot').map(node => node.key))
  const resultKeys = new Set(nodes.filter(node => node.kind === 'video_result').map(node => node.key))
  const owners = new Map<string, string>()
  for (const edge of edges) {
    if (productionKeys.has(edge.source) && resultKeys.has(edge.target) && isVideoResultBinding(edge)) {
      owners.set(edge.target, edge.source)
    }
  }
  return owners
}

export function projectVideoResultEdge(
  edge: WorkbenchEdge,
  owners: ReadonlyMap<string, string>,
): WorkbenchEdge {
  return {
    ...edge,
    source: owners.get(edge.source) ?? edge.source,
    target: owners.get(edge.target) ?? edge.target,
  }
}
