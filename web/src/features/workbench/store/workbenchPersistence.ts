import type { NodeSize, Point, WorkbenchEdge, WorkbenchNode, WorkbenchViewport } from '../types/workbenchTypes'

export const WORKBENCH_LAYOUT_VERSION = 2 as const

export interface SavedNodeLayout {
  position: Point
  size: NodeSize | null
  zIndex: number
  ui: Record<string, unknown>
}

export interface SavedWorkbenchStateV2 {
  version: 2
  viewport: WorkbenchViewport
  canvasSize: { width: number; height: number }
  nodes: Record<string, SavedNodeLayout>
  manualNodes: WorkbenchNode[]
  manualEdges: WorkbenchEdge[]
}

const manualKinds = new Set<WorkbenchNode['kind']>([
  'audio_reference',
  'digital_human',
  'image_media',
  'video_media',
  'audio_media',
  'watermark',
  'video_composer',
  'section',
  'note',
])

export function isManualNodeKind(kind: WorkbenchNode['kind']) {
  return manualKinds.has(kind)
}

export function serializeWorkbenchState(state: SavedWorkbenchStateV2) {
  return JSON.stringify(state)
}

export function parseWorkbenchState(serialized: string): SavedWorkbenchStateV2 | null {
  try {
    const value = JSON.parse(serialized) as Partial<SavedWorkbenchStateV2> & {
      mediaEdges?: WorkbenchEdge[]
      mediaNodes?: WorkbenchNode[]
    }
    if (!value || typeof value !== 'object') return null
    const viewport = value.viewport
    if (!viewport
      || !Number.isFinite(viewport.x)
      || !Number.isFinite(viewport.y)
      || !Number.isFinite(viewport.zoom)) return null
    return {
      version: WORKBENCH_LAYOUT_VERSION,
      viewport,
      canvasSize: value.canvasSize && Number.isFinite(value.canvasSize.width) && Number.isFinite(value.canvasSize.height)
        ? value.canvasSize
        : { width: 0, height: 0 },
      nodes: value.nodes && typeof value.nodes === 'object' ? value.nodes : {},
      manualNodes: (value.manualNodes || value.mediaNodes || []).filter(node => isManualNodeKind(node.kind)),
      manualEdges: Array.isArray(value.manualEdges)
        ? value.manualEdges
        : Array.isArray(value.mediaEdges) ? value.mediaEdges : [],
    }
  } catch {
    return null
  }
}
