import type { InjectionKey } from 'vue'
import type { WorkbenchNode, WorkbenchPromptEditor } from '../types/workbenchTypes'

export interface WorkbenchPromptEditorController {
  close: (nodeKey: string) => void
  focusReference: (nodeKey: string) => void
  removeReference: (edgeKey: string) => void
}

export const workbenchPromptEditorKey: InjectionKey<WorkbenchPromptEditorController> = Symbol('workbench-prompt-editor')

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function assetType(node: WorkbenchNode) {
  const value = node.data.asset_type ?? node.data.assetType
  return typeof value === 'string' ? value : ''
}

export function promptEditorForNode(
  node: WorkbenchNode,
  editors: readonly WorkbenchPromptEditor[],
): WorkbenchPromptEditor | null {
  const editor = editors.find((candidate) => {
    if (candidate.nodeKind !== node.kind)
      return false
    if (candidate.nodeKind !== 'asset')
      return true
    const currentAssetType = assetType(node)
    if (candidate.allowedAssetTypes && !candidate.allowedAssetTypes.includes(currentAssetType))
      return false
    return !candidate.excludedAssetTypes?.includes(currentAssetType)
  })
  return editor ?? null
}

export function promptEditorFromData(value: unknown): WorkbenchPromptEditor | null {
  const editor = record(value)
  if (typeof editor.editorKey !== 'string'
    || (editor.nodeKind !== 'asset' && editor.nodeKind !== 'shot')
    || typeof editor.fieldKey !== 'string'
    || typeof editor.label !== 'string') {
    return null
  }
  return editor as unknown as WorkbenchPromptEditor
}
