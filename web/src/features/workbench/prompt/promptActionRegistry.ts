import type { Component, ComputedRef, InjectionKey, Ref } from 'vue';
import { inject, onScopeDispose, shallowReactive } from 'vue';

type ReactiveValue<T> = Readonly<Ref<T> | ComputedRef<T>>;

export interface WorkbenchPromptActionControl {
  id: string;
  component: Component;
  visible?: ReactiveValue<boolean>;
  props?: ReactiveValue<Record<string, unknown>>;
  modelValue: ReactiveValue<unknown>;
  updateModelValue: (value: unknown) => void;
  events?: Record<string, (payload?: unknown) => void>;
}

export interface WorkbenchPromptAction {
  id: string;
  label: string;
  busyLabel?: string;
  enabled: ReactiveValue<boolean>;
  busy: ReactiveValue<boolean>;
  progress?: ReactiveValue<number | null>;
  cost?: ReactiveValue<number>;
  control?: WorkbenchPromptActionControl;
  controls?: WorkbenchPromptActionControl[];
  run: () => Promise<void> | void;
}

export interface WorkbenchPromptActionRegistry {
  actions: Map<string, WorkbenchPromptAction[]>;
  register: (nodeKey: string, action: WorkbenchPromptAction) => () => void;
}

export const workbenchPromptActionRegistryKey: InjectionKey<WorkbenchPromptActionRegistry>
  = Symbol('workbench-prompt-action-registry');

export function createWorkbenchPromptActionRegistry(): WorkbenchPromptActionRegistry {
  const actions = shallowReactive(new Map<string, WorkbenchPromptAction[]>());
  return {
    actions,
    register(nodeKey, action) {
      const existing = actions.get(nodeKey) ?? [];
      actions.set(nodeKey, [...existing.filter(item => item.id !== action.id), action]);
      return () => {
        const next = (actions.get(nodeKey) ?? []).filter(item => item !== action);
        if (next.length)
          actions.set(nodeKey, next);
        else
          actions.delete(nodeKey);
      };
    },
  };
}

export function registerWorkbenchPromptAction(nodeKey: string, action: WorkbenchPromptAction) {
  const registry = inject(workbenchPromptActionRegistryKey, null);
  if (!registry)
    return;
  onScopeDispose(registry.register(nodeKey, action));
}
