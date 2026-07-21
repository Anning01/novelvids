import type { InjectionKey } from 'vue'

export interface WorkbenchSectionActions {
  fitToContent: (sectionKey: string) => Promise<void>
}

export const workbenchSectionActionsKey: InjectionKey<WorkbenchSectionActions> = Symbol('workbench-section-actions')
