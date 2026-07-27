import type { InjectionKey } from 'vue'

export interface KeyboardHandleActivation {
  nodeId: string
  handleId: string
  type: 'source' | 'target'
}

export interface WorkbenchKeyboardConnector {
  activateHandle: (handle: KeyboardHandleActivation) => void
  cancel: () => void
}

export const workbenchKeyboardConnectorKey: InjectionKey<WorkbenchKeyboardConnector> = Symbol('workbench-keyboard-connector')
