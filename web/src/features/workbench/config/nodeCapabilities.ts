import type { WorkbenchNodeKind } from '../types/workbenchTypes'

export interface WorkbenchNodeCapabilities {
  deletable: boolean
  copyable: boolean
  runnable: boolean
  target: boolean
  source: boolean
}

export const NODE_CAPABILITIES: Record<WorkbenchNodeKind, WorkbenchNodeCapabilities> = {
  chapter: { deletable: false, copyable: false, runnable: false, target: false, source: true },
  asset: { deletable: true, copyable: false, runnable: true, target: true, source: true },
  audio_reference: { deletable: true, copyable: false, runnable: false, target: false, source: true },
  digital_human: { deletable: true, copyable: false, runnable: false, target: false, source: true },
  image_media: { deletable: true, copyable: false, runnable: false, target: false, source: true },
  video_media: { deletable: true, copyable: false, runnable: false, target: false, source: true },
  audio_media: { deletable: true, copyable: false, runnable: false, target: false, source: true },
  shot: { deletable: true, copyable: true, runnable: true, target: true, source: true },
  video_result: { deletable: true, copyable: false, runnable: false, target: true, source: true },
  watermark: { deletable: true, copyable: false, runnable: true, target: true, source: true },
  video_composer: { deletable: true, copyable: false, runnable: true, target: true, source: true },
  section: { deletable: true, copyable: false, runnable: false, target: false, source: false },
  note: { deletable: true, copyable: true, runnable: false, target: false, source: false },
  unsupported: { deletable: false, copyable: false, runnable: false, target: false, source: false },
}

export function nodeCapabilities(kind: WorkbenchNodeKind | undefined) {
  return NODE_CAPABILITIES[kind || 'unsupported']
}
