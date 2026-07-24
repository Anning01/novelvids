import type { WorkbenchViewport } from '../types/workbenchTypes';

interface WorkbenchViewportFocus {
  centerX: number;
  centerY: number;
  zoom: number;
}

interface ViewportSize {
  width: number;
  height: number;
}

const STORAGE_PREFIX = 'novel-workbench:viewport:v1:';
export const WORKBENCH_MIN_ZOOM = 0.15;
export const WORKBENCH_MAX_ZOOM = 4;

function validNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function viewportToFocus(viewport: WorkbenchViewport, size: ViewportSize): WorkbenchViewportFocus {
  const zoom = Math.max(0.01, viewport.zoom);
  return {
    centerX: (size.width / 2 - viewport.x) / zoom,
    centerY: (size.height / 2 - viewport.y) / zoom,
    zoom,
  };
}

export function focusToViewport(focus: WorkbenchViewportFocus, size: ViewportSize): WorkbenchViewport {
  return {
    x: size.width / 2 - focus.centerX * focus.zoom,
    y: size.height / 2 - focus.centerY * focus.zoom,
    zoom: focus.zoom,
  };
}

export function saveWorkbenchViewport(workspaceKey: string, viewport: WorkbenchViewport, size: ViewportSize): void {
  if (!workspaceKey || size.width <= 0 || size.height <= 0)
    return;
  try {
    globalThis.localStorage?.setItem(`${STORAGE_PREFIX}${workspaceKey}`, JSON.stringify(viewportToFocus(viewport, size)));
  }
  catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
}

export function loadWorkbenchViewport(workspaceKey: string, size: ViewportSize): WorkbenchViewport | null {
  if (!workspaceKey || size.width <= 0 || size.height <= 0)
    return null;
  try {
    const serialized = globalThis.localStorage?.getItem(`${STORAGE_PREFIX}${workspaceKey}`);
    if (!serialized)
      return null;
    const focus = JSON.parse(serialized) as Partial<WorkbenchViewportFocus>;
    if (!validNumber(focus.centerX) || !validNumber(focus.centerY) || !validNumber(focus.zoom) || focus.zoom < WORKBENCH_MIN_ZOOM || focus.zoom > WORKBENCH_MAX_ZOOM)
      return null;
    return focusToViewport(focus as WorkbenchViewportFocus, size);
  }
  catch {
    return null;
  }
}
