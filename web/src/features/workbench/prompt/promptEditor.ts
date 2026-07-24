import type { InjectionKey, Ref } from 'vue'

export interface WorkbenchPromptEditorController {
  activeNodeKey: Ref<string | null>
  open: (nodeKey: string) => void
  close: (nodeKey?: string) => void
}

export const workbenchPromptEditorKey: InjectionKey<WorkbenchPromptEditorController> = Symbol('workbench-prompt-editor')
