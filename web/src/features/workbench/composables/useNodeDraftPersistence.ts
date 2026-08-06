import type { useWorkbenchStore } from '../store/workbenchStore';
import { onBeforeUnmount } from 'vue';

type WorkbenchStore = ReturnType<typeof useWorkbenchStore>;

interface NodeDraftPersistenceOptions {
  debounceMs?: number;
  onError?: (error: unknown) => void;
}

export function useNodeDraftPersistence(
  store: WorkbenchStore,
  nodeKey: () => string,
  options: NodeDraftPersistenceOptions = {},
) {
  const debounceMs = options.debounceMs ?? 800;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function report(error: unknown) {
    options.onError?.(error);
  }

  async function flush() {
    clearTimeout(timer);
    timer = undefined;
    return store.flushNodeDraft(nodeKey());
  }

  function flushInBackground() {
    void flush().catch(report);
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(flushInBackground, debounceMs);
  }

  function handleFocusOut(event: FocusEvent) {
    const container = event.currentTarget as HTMLElement | null;
    const next = event.relatedTarget as Node | null;
    if (container && next && container.contains(next))
      return;
    clearTimeout(timer);
    timer = setTimeout(flushInBackground, 0);
  }

  onBeforeUnmount(() => {
    clearTimeout(timer);
    timer = undefined;
    flushInBackground();
  });

  return { flush, handleFocusOut, schedule };
}
