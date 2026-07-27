import type { ComputedRef, InjectionKey, Ref } from 'vue';
import { inject, onScopeDispose, shallowReactive } from 'vue';

export interface WorkbenchNodeRunCommand {
  enabled: Readonly<Ref<boolean> | ComputedRef<boolean>>;
  run: () => Promise<void> | void;
}

export interface WorkbenchNodeRunRegistry {
  commands: Map<string, WorkbenchNodeRunCommand>;
  register: (nodeKey: string, command: WorkbenchNodeRunCommand) => () => void;
}

export const workbenchNodeRunRegistryKey: InjectionKey<WorkbenchNodeRunRegistry> = Symbol('workbench-node-run-registry');

export function createWorkbenchNodeRunRegistry(): WorkbenchNodeRunRegistry {
  const commands = shallowReactive(new Map<string, WorkbenchNodeRunCommand>());
  return {
    commands,
    register(nodeKey, command) {
      commands.set(nodeKey, command);
      return () => {
        if (commands.get(nodeKey) === command)
          commands.delete(nodeKey);
      };
    },
  };
}

export function registerWorkbenchNodeRun(nodeKey: string, command: WorkbenchNodeRunCommand) {
  const registry = inject(workbenchNodeRunRegistryKey, null);
  if (!registry)
    return;
  onScopeDispose(registry.register(nodeKey, command));
}
