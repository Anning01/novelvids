# Wireless Canvas Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local wireless canvas match the verified Shengshi Media workbench in canvas behavior, toolbar states, node configuration, media tooling, and button-by-button regression behavior.

**Architecture:** Stabilize one named Vue Flow instance and a bidirectional selection adapter first, then build viewport, bounded layout, history, and typed persisted node contracts on top. UI parity is added as focused components; existing backend generation APIs remain authoritative, while a capability endpoint truthfully disables unsupported watermark/composition execution instead of fabricating results.

**Tech Stack:** Vue 3.5, TypeScript 6, Pinia 3, Vue Flow 1.48.2, Vite 8, Vitest, Vue Test Utils, FastAPI, Pydantic, Tortoise ORM, pytest, Chrome control.

## Global Constraints

- Use the single exact flow id `novel-workbench` in both `<VueFlow>` and `useVueFlow(WORKBENCH_FLOW_ID)`.
- Keep toolbar icon buttons at `34px` and preserve the project-specific “故事板 / 工作流” switch.
- Offer shot ratios `16:9`, `9:16`, `1:1`, `4:3`, `3:4` and resolutions `480p`, `720p`, `1080p`.
- Keep Shengshi Media menu items in the main group and “参考音频 / 数字人” in a separate project-resource group.
- Do not trigger paid generation, composition, watermarking, or external uploads during automated browser regression.
- Do not display successful media output unless a real backend response supplies it.
- Migrate existing `layout:v1` browser data without losing node positions, notes, sections, or media connections.
- Preserve the existing unrelated dirty worktree. Before every commit, stage only task-owned paths and inspect `git diff --cached --name-only`; if a pre-existing dirty hunk cannot be isolated safely, leave that file unstaged and defer its commit.
- Every task finishes with its targeted test, `npm run typecheck` when frontend types change, and a focused commit when the staged diff is isolated.

---

## File Structure

### New frontend files

- `web/vitest.config.ts` — Vitest and Vue SFC test configuration.
- `web/src/test/setup.ts` — deterministic DOM shims and test cleanup.
- `web/src/features/workbench/runtime/workbenchFlowRuntime.ts` — flow id and ready-state helpers.
- `web/src/features/workbench/interaction/workbenchSelection.ts` — pure selection reconciliation.
- `web/src/features/workbench/viewport/workbenchCoordinates.ts` — screen-center and visible-placement calculations.
- `web/src/features/workbench/store/workbenchPersistence.ts` — versioned layout serialization and v1 migration.
- `web/src/features/workbench/execution/workbenchCapabilities.ts` — run eligibility and disabled reasons.
- `web/src/features/workbench/config/assetConfig.ts` — asset metadata normalization.
- `web/src/features/workbench/config/shotConfig.ts` — shot metadata normalization and model-aware options.
- `web/src/features/workbench/components/WorkbenchCanvasIdentity.vue` — editable canvas/chapter identity.
- `web/src/features/workbench/components/ImageAnnotationDialog.vue` — image annotation editor.
- `web/src/features/workbench/components/WatermarkSettingsDialog.vue` — watermark resource and placement controls.
- `web/src/features/workbench/nodes/ImageMediaNode.vue` — uploaded image and annotation entry.
- `web/src/features/workbench/nodes/VideoMediaNode.vue` — uploaded video preview.
- `web/src/features/workbench/nodes/AudioMediaNode.vue` — uploaded audio preview.
- `web/src/features/workbench/nodes/WatermarkNode.vue` — watermark configuration and output.
- `web/src/features/workbench/nodes/VideoComposerNode.vue` — ordered clip composition configuration.
- Focused `*.test.ts` and `*.spec.ts` files colocated with the units above.

### Modified frontend files

- `web/package.json`, `web/package-lock.json` — frontend test dependencies and script.
- `web/src/api.ts`, `web/src/types.ts` — chapter patch, upload response, capability contracts, expanded asset types.
- `web/src/features/workbench/types/workbenchTypes.ts` — typed node kinds/configuration.
- `web/src/features/workbench/pages/CreativeCanvas.vue` — named flow instance, adapters, node registry, upload inputs, orchestration.
- `web/src/features/workbench/store/workbenchStore.ts` — typed actions, selection, history, media nodes, watermark/composer state.
- `web/src/features/workbench/layout/workbenchAutoLayout.ts` — bounded multi-column packing and fixed nodes.
- `web/src/features/workbench/components/WorkbenchToolbar.vue` — reference menu, tooltips, dynamic run CTA.
- `web/src/features/workbench/components/WorkbenchNodeFrame.vue` — capability-driven node actions and explicit-key deletion.
- `web/src/features/workbench/components/MediaLibraryPicker.vue` — search reset/race correction.
- `web/src/features/workbench/nodes/AssetNode.vue` — reference-equivalent asset controls and versions.
- `web/src/features/workbench/nodes/ShotNode.vue` — reference-equivalent shot controls and warning-free root.
- `web/src/features/workbench/styles/workbench.css` — matched dimensions, new node/dialog styles, responsive behavior.
- `web/src/pages/ShortDramaStoryboardPage.vue` — pass canvas identity and preserve switch layering.

### New backend files

- `schemas/workbench.py` — capability response model.
- `api/workbench.py` — `GET /api/workbench/capabilities`.
- `test/test_api/test_workbench_api.py` — capability contract test.

### Modified backend files

- `api/__init__.py` — register workbench route.
- `utils/enums.py` — add `product=4` and `style=5`.
- `test/test_api/test_asset_api.py` — verify expanded asset kinds.

---

### Task 1: Install the Frontend Test Harness and Flow Runtime Contract

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Create: `web/vitest.config.ts`
- Create: `web/src/test/setup.ts`
- Create: `web/src/features/workbench/runtime/workbenchFlowRuntime.ts`
- Test: `web/src/features/workbench/runtime/workbenchFlowRuntime.test.ts`

**Interfaces:**
- Produces: `WORKBENCH_FLOW_ID: 'novel-workbench'`
- Produces: `isWorkbenchFlowReady(dimensions: { width: number; height: number }): boolean`

- [ ] **Step 1: Add the test dependencies and script**

Run:

```bash
cd web
npm install --save-dev vitest @vue/test-utils jsdom
```

Add `"test": "vitest run"` under `scripts`.

- [ ] **Step 2: Configure Vitest**

Create `web/vitest.config.ts`:

```ts
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
  },
})
```

Create `web/src/test/setup.ts`:

```ts
import { enableAutoUnmount } from '@vue/test-utils'
import { afterEach } from 'vitest'

enableAutoUnmount(afterEach)
Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
  configurable: true,
  value() {},
})
```

- [ ] **Step 3: Write the failing runtime contract test**

```ts
import { describe, expect, it } from 'vitest'
import { isWorkbenchFlowReady, WORKBENCH_FLOW_ID } from './workbenchFlowRuntime'

describe('workbench flow runtime', () => {
  it('uses the one public flow id', () => {
    expect(WORKBENCH_FLOW_ID).toBe('novel-workbench')
  })

  it('rejects an unmeasured viewport', () => {
    expect(isWorkbenchFlowReady({ width: 0, height: 720 })).toBe(false)
    expect(isWorkbenchFlowReady({ width: 1280, height: 720 })).toBe(true)
  })
})
```

- [ ] **Step 4: Run the test and verify the missing module failure**

Run: `cd web && npm run test -- src/features/workbench/runtime/workbenchFlowRuntime.test.ts`

Expected: FAIL because `workbenchFlowRuntime.ts` does not exist.

- [ ] **Step 5: Implement the runtime contract**

```ts
export const WORKBENCH_FLOW_ID = 'novel-workbench' as const

export function isWorkbenchFlowReady(dimensions: { width: number; height: number }) {
  return Number.isFinite(dimensions.width)
    && Number.isFinite(dimensions.height)
    && dimensions.width > 0
    && dimensions.height > 0
}
```

- [ ] **Step 6: Verify and commit**

Run:

```bash
cd web
npm run test -- src/features/workbench/runtime/workbenchFlowRuntime.test.ts
npm run typecheck
```

Expected: both commands pass.

Commit:

```bash
git add web/package.json web/package-lock.json web/vitest.config.ts web/src/test/setup.ts web/src/features/workbench/runtime
git commit -m "test: add workbench frontend harness"
```

### Task 2: Publish Truthful Backend Capabilities and Asset Types

**Files:**
- Create: `schemas/workbench.py`
- Create: `api/workbench.py`
- Modify: `api/__init__.py`
- Modify: `utils/enums.py`
- Test: `test/test_api/test_workbench_api.py`
- Test: `test/test_api/test_asset_api.py`
- Modify: `web/src/api.ts`
- Modify: `web/src/types.ts`

**Interfaces:**
- Produces: `GET /api/workbench/capabilities`
- Produces: `WorkbenchCapabilities { upload_media; generate_asset; generate_video; apply_watermark; compose_video }`
- Produces: `api.updateChapter(id, patch)`
- Produces: upload fields `original_filename`, `content_type`, `filename`, `file_path`

- [ ] **Step 1: Write failing API tests**

```py
import pytest
from httpx import AsyncClient
from models.novel import Novel


@pytest.mark.asyncio
async def test_workbench_capabilities(client):
    response = await client.get("/api/workbench/capabilities")
    assert response.status_code == 200
    assert response.json()["data"] == {
        "upload_media": True,
        "generate_asset": True,
        "generate_video": True,
        "apply_watermark": False,
        "compose_video": False,
    }


@pytest.mark.asyncio
async def test_create_product_asset(client: AsyncClient):
    novel = await Novel.create(name="Product Asset Novel", author="Author")
    response = await client.post("/api/asset", json={
        "novel_id": novel.id,
        "asset_type": 4,
        "canonical_name": "示例商品",
    })
    assert response.status_code == 200
    assert response.json()["data"]["asset_type"] == 4
```

- [ ] **Step 2: Run the focused backend tests**

Run:

```bash
uv run pytest test/test_api/test_workbench_api.py test/test_api/test_asset_api.py -q
```

Expected: capability route and asset type 4 tests fail.

- [ ] **Step 3: Add the schema and route**

`schemas/workbench.py`:

```py
from pydantic import BaseModel


class WorkbenchCapabilitiesOut(BaseModel):
    upload_media: bool = True
    generate_asset: bool = True
    generate_video: bool = True
    apply_watermark: bool = False
    compose_video: bool = False
```

`api/workbench.py`:

```py
from fastapi import APIRouter
from schemas.workbench import WorkbenchCapabilitiesOut
from utils.response_format import ResponseSchema

router = APIRouter()


@router.get("/capabilities", response_model=ResponseSchema[WorkbenchCapabilitiesOut])
async def get_workbench_capabilities():
    return ResponseSchema(data=WorkbenchCapabilitiesOut())
```

Register it in `api/__init__.py` at prefix `/workbench`.

- [ ] **Step 4: Extend the asset enum without changing existing values**

```py
class AssetTypeEnum(NicknameIntEnum):
    person = 1, "人物"
    scene = 2, "场景"
    item = 3, "物品"
    product = 4, "商品"
    style = 5, "风格"
```

- [ ] **Step 5: Add frontend contracts**

```ts
export enum AssetTypeEnum {
  PERSON = 1,
  SCENE = 2,
  ITEM = 3,
  PRODUCT = 4,
  STYLE = 5,
}

export interface WorkbenchCapabilities {
  upload_media: boolean
  generate_asset: boolean
  generate_video: boolean
  apply_watermark: boolean
  compose_video: boolean
}
```

Add:

```ts
workbenchCapabilities: () =>
  request<SingleResponse<WorkbenchCapabilities>>('/workbench/capabilities'),
updateChapter: (id: number, data: Partial<Chapter>) =>
  request<SingleResponse<Chapter>>(`/chapter/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  }),
```

Return `original_filename` and `content_type` from `api.upload`.

- [ ] **Step 6: Verify and commit**

Run:

```bash
uv run pytest test/test_api/test_workbench_api.py test/test_api/test_asset_api.py -q
cd web
npm run typecheck
```

Expected: all pass.

Commit:

```bash
git add schemas/workbench.py api/workbench.py api/__init__.py utils/enums.py test/test_api/test_workbench_api.py test/test_api/test_asset_api.py web/src/api.ts web/src/types.ts
git commit -m "feat: expose workbench capabilities"
```

### Task 3: Bind Selection and Viewport Actions to One Vue Flow Instance

**Files:**
- Create: `web/src/features/workbench/interaction/workbenchSelection.ts`
- Test: `web/src/features/workbench/interaction/workbenchSelection.test.ts`
- Modify: `web/src/features/workbench/pages/CreativeCanvas.vue`
- Modify: `web/src/features/workbench/store/workbenchStore.ts`

**Interfaces:**
- Consumes: `WORKBENCH_FLOW_ID`
- Produces: `applyNodeSelectionChanges(current, changes, validKeys): string[]`
- Produces: `sameSelection(left, right): boolean`
- Produces: locked mode that disables drag/connect while retaining node selection and canvas pan.

- [ ] **Step 1: Write selection reconciliation tests**

```ts
import { describe, expect, it } from 'vitest'
import { applyNodeSelectionChanges } from './workbenchSelection'

describe('applyNodeSelectionChanges', () => {
  const valid = new Set(['a', 'b', 'c'])

  it('applies selects and deselects from one event batch', () => {
    expect(applyNodeSelectionChanges(['a'], [
      { id: 'a', type: 'select', selected: false },
      { id: 'b', type: 'select', selected: true },
    ], valid)).toEqual(['b'])
  })

  it('keeps native multi-selection order and drops stale keys', () => {
    expect(applyNodeSelectionChanges(['a', 'missing'], [
      { id: 'c', type: 'select', selected: true },
    ], valid)).toEqual(['a', 'c'])
  })
})
```

- [ ] **Step 2: Run the test and confirm failure**

Run: `cd web && npm run test -- src/features/workbench/interaction/workbenchSelection.test.ts`

Expected: FAIL because the module is missing.

- [ ] **Step 3: Implement the pure adapter**

```ts
import type { NodeChange } from '@vue-flow/core'

export function applyNodeSelectionChanges(
  current: string[],
  changes: NodeChange[],
  validKeys: ReadonlySet<string>,
) {
  const selected = new Set(current.filter(key => validKeys.has(key)))
  for (const change of changes) {
    if (change.type !== 'select' || !validKeys.has(change.id)) continue
    if (change.selected) selected.add(change.id)
    else selected.delete(change.id)
  }
  return [...selected]
}

export function sameSelection(left: string[], right: string[]) {
  return left.length === right.length && left.every((key, index) => key === right[index])
}
```

- [ ] **Step 4: Use the named instance and exact event batch**

In `CreativeCanvas.vue`:

```ts
const {
  fitView,
  getNodes,
  getViewport,
  panBy,
  screenToFlowCoordinate,
  setViewport,
  userSelectionRect,
  viewport,
  vueFlowRef,
} = useVueFlow(WORKBENCH_FLOW_ID)

function handleNodesChange(changes: NodeChange[]) {
  const next = applyNodeSelectionChanges(
    store.selectedNodeKeys,
    changes,
    new Set(store.nodes.map(node => node.key)),
  )
  if (!sameSelection(next, store.selectedNodeKeys)) store.selectNodes(next)
}
```

Bind `<VueFlow :id="WORKBENCH_FLOW_ID">`.

- [ ] **Step 5: Make lock behavior explicit**

Do not use Vue Flow Controls’ `setInteractive`, because it also disables selection. Keep the built-in zoom/fit controls, hide its interactive button, and add a controlled lock button:

```ts
const canvasLocked = ref(false)
const nodesDraggable = computed(() => !canvasLocked.value && !panModeActive.value)
const nodesConnectable = computed(() => !canvasLocked.value)
```

```vue
<VueFlow
  :nodes-draggable="nodesDraggable"
  :nodes-connectable="nodesConnectable"
  :elements-selectable="true"
>
  <Controls position="bottom-right" :show-interactive="false">
    <button
      class="vue-flow__controls-button vue-flow__controls-interactive"
      type="button"
      :aria-pressed="canvasLocked"
      :aria-label="canvasLocked ? '解锁画布编辑' : '锁定画布编辑'"
      @click="canvasLocked = !canvasLocked"
    >
      <Lock v-if="canvasLocked" :size="14" />
      <Unlock v-else :size="14" />
    </button>
  </Controls>
</VueFlow>
```

- [ ] **Step 6: Verify the adapter and types**

Run:

```bash
cd web
npm run test -- src/features/workbench/interaction/workbenchSelection.test.ts
npm run typecheck
```

Expected: pass with no Vue Flow instance overload errors.

- [ ] **Step 7: Browser-check the fixed root cause**

In Chrome local workbench:

- Click one shot: toolbar delete/copy become enabled.
- Shift-click a note: both node toolbars remain selected and “创建分区” enables.
- Click blank canvas: both Pinia-driven tool states disable.
- Click fit view: console contains no `Viewport not initialized yet`.
- Lock the canvas: node selection still works, node drag/connect do not, and pan still works.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/workbench/runtime/workbenchFlowRuntime.ts web/src/features/workbench/interaction/workbenchSelection.ts web/src/features/workbench/interaction/workbenchSelection.test.ts
git add -p web/src/features/workbench/pages/CreativeCanvas.vue web/src/features/workbench/store/workbenchStore.ts
git commit -m "fix: synchronize workbench selection"
```

### Task 4: Place New Nodes in the Visible Viewport and Restore View Safely

**Files:**
- Create: `web/src/features/workbench/viewport/workbenchCoordinates.ts`
- Test: `web/src/features/workbench/viewport/workbenchCoordinates.test.ts`
- Test: `web/src/features/workbench/viewport/workbenchViewportPersistence.test.ts`
- Modify: `web/src/features/workbench/pages/CreativeCanvas.vue`
- Modify: `web/src/features/workbench/store/workbenchStore.ts`

**Interfaces:**
- Produces: `screenPointForCenteredNode(bounds, size): Point`
- Consumes: Vue Flow `screenToFlowCoordinate(point)`
- Produces: `store.addShot(position): Promise<WorkbenchNode | null>`

- [ ] **Step 1: Write the screen-center test**

```ts
import { expect, it } from 'vitest'
import { screenPointForCenteredNode } from './workbenchCoordinates'

it('centers a node in canvas client coordinates', () => {
  expect(screenPointForCenteredNode(
    { left: 100, top: 40, width: 1200, height: 800 },
    { width: 360, height: 520 },
  )).toEqual({ x: 520, y: 180 })
})
```

Also create `workbenchViewportPersistence.test.ts`:

```ts
import { expect, it } from 'vitest'
import { focusToViewport, viewportToFocus } from './workbenchViewportPersistence'

it('preserves the flow-space center when the canvas resizes', () => {
  const focus = viewportToFocus(
    { x: -200, y: -100, zoom: 0.5 },
    { width: 1200, height: 800 },
  )
  const resized = focusToViewport(focus, { width: 1600, height: 900 })
  expect(viewportToFocus(resized, { width: 1600, height: 900 })).toEqual(focus)
})
```

- [ ] **Step 2: Run the test and confirm failure**

Run: `cd web && npm run test -- src/features/workbench/viewport/workbenchCoordinates.test.ts`

Expected: missing module failure.

- [ ] **Step 3: Implement screen placement**

```ts
export function screenPointForCenteredNode(
  bounds: { left: number; top: number; width: number; height: number },
  size: { width: number; height: number },
) {
  return {
    x: Math.round(bounds.left + Math.max(24, (bounds.width - size.width) / 2)),
    y: Math.round(bounds.top + Math.max(64, (bounds.height - size.height) / 2)),
  }
}
```

- [ ] **Step 4: Replace manual viewport math**

```ts
function visibleNodePosition(size: NodeSize) {
  const bounds = vueFlowRef.value?.getBoundingClientRect()
  if (!bounds || !isWorkbenchFlowReady(bounds)) return { x: 80, y: 80 }
  return screenToFlowCoordinate(screenPointForCenteredNode(bounds, size))
}

async function addShot() {
  const created = await store.addShot(visibleNodePosition({ width: 360, height: 520 }))
  if (created) await ensureNodeVisible(created.key)
}
```

Move initial viewport restore to the Vue Flow `nodes-initialized` event, guard it so each chapter restores once, and remove fixed-time waiting.

- [ ] **Step 5: Make `addShot` return and select the real node**

```ts
async addShot(position?: Point) {
  const created = (await api.createScene({
    chapter_id: this.chapterId,
    sequence: Math.max(0, ...this.scenes.map(scene => scene.sequence)) + 1,
    description: '新镜头',
    prompt: '',
    duration: 6,
  })).data
  this.scenes.push(created)
  this.videos[created.id] = []
  this.rebuildGraph()
  const item = this.nodeByKey(`shot-${created.id}`) || null
  if (item && position) item.position = position
  if (item) this.selectNode(item.key)
  this.persistLayout()
  return item
}
```

- [ ] **Step 6: Verify**

Run:

```bash
cd web
npm run test -- src/features/workbench/viewport/workbenchCoordinates.test.ts src/features/workbench/viewport/workbenchViewportPersistence.test.ts
npm run typecheck
```

In Chrome, pan and zoom away from the origin, add a note and a shot, and verify both appear inside the current viewport and are selected.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/workbench/viewport/workbenchCoordinates.ts web/src/features/workbench/viewport/workbenchCoordinates.test.ts web/src/features/workbench/viewport/workbenchViewportPersistence.test.ts
git add -p web/src/features/workbench/pages/CreativeCanvas.vue web/src/features/workbench/store/workbenchStore.ts
git commit -m "fix: create workbench nodes in view"
```

### Task 5: Pack Large Graphs into Readable Multi-Column Layouts

**Files:**
- Modify: `web/src/features/workbench/layout/workbenchAutoLayout.ts`
- Test: `web/src/features/workbench/layout/workbenchAutoLayout.test.ts`
- Modify: `web/src/features/workbench/pages/CreativeCanvas.vue`

**Interfaces:**
- Extends: `WorkbenchAutoLayoutOptions.maxColumnHeight?: number`
- Extends: `WorkbenchAutoLayoutOptions.fixedNodeKeys?: ReadonlySet<string>`
- Produces: deterministic, non-overlapping positions

- [ ] **Step 1: Add the 15-shot and fixed-node tests**

```ts
import { expect, it } from 'vitest'
import type { Point, WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import { buildWorkbenchAutoLayout } from './workbenchAutoLayout'

const timestamp = '2026-07-25T00:00:00.000Z'

function makeNode(key: string, position: Point, kind: WorkbenchNode['kind'] = 'shot'): WorkbenchNode {
  return {
    id: Number(key.replace(/\D/g, '')) || -1,
    key,
    kind,
    backendKind: kind,
    title: key,
    position,
    size: { width: 360, height: 520 },
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: { layout_family: kind === 'shot' ? 'shot' : kind, ui: {} },
    createdAt: timestamp,
    updatedAt: timestamp,
  }
}

function makeShotNodes(count: number, size: { width: number; height: number }) {
  return Array.from({ length: count }, (_, index) => ({
    ...makeNode(`shot-${index + 1}`, { x: 0, y: index * 20 }),
    size,
    data: { layout_family: 'shot', shot_index: index + 1, ui: {} },
  }))
}

function makeSequenceEdges(nodes: WorkbenchNode[]): WorkbenchEdge[] {
  return nodes.slice(1).map((node, index) => ({
    id: index + 1,
    key: `sequence-${index}`,
    source: nodes[index]!.key,
    target: node.key,
    type: 'shot_sequence',
    backendType: 'shot_sequence',
    sourceHandle: null,
    targetHandle: null,
    orderIndex: index,
    config: null,
    createdAt: timestamp,
    updatedAt: timestamp,
  }))
}

function expectNoOverlaps(nodes: WorkbenchNode[], positions: Record<string, Point>) {
  for (let leftIndex = 0; leftIndex < nodes.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < nodes.length; rightIndex += 1) {
      const left = nodes[leftIndex]!
      const right = nodes[rightIndex]!
      const leftPosition = positions[left.key]!
      const rightPosition = positions[right.key]!
      const separated = leftPosition.x + left.size!.width <= rightPosition.x
        || rightPosition.x + right.size!.width <= leftPosition.x
        || leftPosition.y + left.size!.height <= rightPosition.y
        || rightPosition.y + right.size!.height <= leftPosition.y
      expect(separated, `${left.key} overlaps ${right.key}`).toBe(true)
    }
  }
}

it('wraps fifteen shots into bounded readable columns', () => {
  const nodes = makeShotNodes(15, { width: 360, height: 520 })
  const positions = buildWorkbenchAutoLayout(nodes, makeSequenceEdges(nodes), {
    maxColumnHeight: 1800,
  })
  const distinctX = new Set(nodes.map(node => positions[node.key]!.x))
  expect(distinctX.size).toBeGreaterThanOrEqual(5)
  expect(Math.max(...nodes.map(node => positions[node.key]!.y))).toBeLessThan(1800)
  expectNoOverlaps(nodes, positions)
})

it('does not move fixed nodes', () => {
  const nodes = [makeNode('fixed', { x: 740, y: 310 }), makeNode('free', { x: 0, y: 0 })]
  const positions = buildWorkbenchAutoLayout(nodes, [], {
    fixedNodeKeys: new Set(['fixed']),
  })
  expect(positions.fixed).toEqual({ x: 740, y: 310 })
})
```

- [ ] **Step 2: Verify both tests fail**

Run: `cd web && npm run test -- src/features/workbench/layout/workbenchAutoLayout.test.ts`

Expected: the shot lane remains one tall column and fixed nodes move.

- [ ] **Step 3: Add bounded lane packing**

Implement:

```ts
function packLane(
  nodes: WorkbenchNode[],
  sizes: Record<string, NodeSize>,
  rowGap: number,
  maxColumnHeight: number,
) {
  const columns: WorkbenchNode[][] = []
  let height = 0
  for (const node of nodes) {
    const nextHeight = height + (height ? rowGap : 0) + sizes[node.key]!.height
    if (height && nextHeight > maxColumnHeight) {
      columns.push([])
      height = 0
    }
    if (!columns.length) columns.push([])
    columns.at(-1)!.push(node)
    height += (height ? rowGap : 0) + sizes[node.key]!.height
  }
  return columns
}
```

Pack shot/result lanes when their height exceeds the bound, preserve sequence order, and keep fixed nodes at their input coordinates.

- [ ] **Step 4: Pass current canvas height to layout**

In `autoArrange()`:

```ts
const { height } = canvasSize()
const fixedNodeKeys = new Set(store.nodes
  .filter(node => node.zIndex >= 1_000_000 || node.data.ui?.locked === true)
  .map(node => node.key))
const positions = buildWorkbenchGroupedAutoLayout(store.nodes, store.edges, {
  sizes: measuredSizes,
  maxColumnHeight: Math.max(1100, height * 2.2),
  fixedNodeKeys,
})
```

Wait for the correct instance’s node dimensions before `fitView`.

- [ ] **Step 5: Verify**

Run:

```bash
cd web
npm run test -- src/features/workbench/layout/workbenchAutoLayout.test.ts
npm run typecheck
```

In Chrome with the verified 15-shot chapter, auto-layout and confirm cards remain readable and form multiple columns.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/workbench/layout/workbenchAutoLayout.ts web/src/features/workbench/layout/workbenchAutoLayout.test.ts
git add -p web/src/features/workbench/pages/CreativeCanvas.vue
git commit -m "fix: bound workbench auto layout"
```

### Task 6: Version Persistence, History, Clipboard, and Explicit Deletion

**Files:**
- Create: `web/src/features/workbench/store/workbenchPersistence.ts`
- Test: `web/src/features/workbench/store/workbenchPersistence.test.ts`
- Test: `web/src/features/workbench/store/workbenchStore.test.ts`
- Modify: `web/src/features/workbench/types/workbenchTypes.ts`
- Modify: `web/src/features/workbench/store/workbenchStore.ts`
- Modify: `web/src/features/workbench/components/WorkbenchNodeFrame.vue`
- Modify: `web/src/features/workbench/nodes/NoteNode.vue`

**Interfaces:**
- Produces: `WORKBENCH_LAYOUT_VERSION = 2`
- Produces: `serializeWorkbenchState(state): string`
- Produces: `parseWorkbenchState(serialized): SavedWorkbenchStateV2 | null`
- Produces: `isManualNodeKind(kind): boolean`
- Produces: `deleteNodeKeys(keys: string[]): Promise<number>`

- [ ] **Step 1: Write migration and store failure tests**

In `workbenchPersistence.test.ts`:

```ts
import { expect, it } from 'vitest'
import type { WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import { parseWorkbenchState } from './workbenchPersistence'

const timestamp = '2026-07-25T00:00:00.000Z'
const note = {
  id: -1,
  key: 'note-1',
  kind: 'note',
  backendKind: 'note',
  title: '便签',
  position: { x: 20, y: 30 },
  size: { width: 320, height: 220 },
  zIndex: 1,
  activeVersionId: null,
  status: 'ready',
  data: { content: '内容', color: '#8d793d', ui: {} },
  createdAt: timestamp,
  updatedAt: timestamp,
} satisfies WorkbenchNode
const mediaEdge = {
  id: -2,
  key: 'media-edge-1',
  source: 'note-1',
  target: 'shot-1',
  type: 'asset_reference',
  backendType: 'asset_reference',
  sourceHandle: null,
  targetHandle: null,
  orderIndex: 0,
  config: null,
  createdAt: timestamp,
  updatedAt: timestamp,
} satisfies WorkbenchEdge

it('migrates layout v1 manual nodes and media edges', () => {
  const parsed = parseWorkbenchState(JSON.stringify({
    viewport: { x: 2, y: 3, zoom: 1 },
    manualNodes: [note],
    mediaEdges: [mediaEdge],
  }))
  expect(parsed?.version).toBe(2)
  expect(parsed?.manualNodes[0]?.key).toBe('note-1')
  expect(parsed?.manualEdges[0]?.key).toBe('media-edge-1')
})
```

In `workbenchStore.test.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { useWorkbenchStore } from './workbenchStore'

vi.mock('@/api', () => ({
  api: { createScene: vi.fn() },
  sleep: vi.fn(),
}))

const createSceneMock = vi.mocked(api.createScene)
let store: ReturnType<typeof useWorkbenchStore>

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkbenchStore()
  store.chapterId = 2162
})

it('does not leave a shot when createScene rejects', async () => {
  createSceneMock.mockRejectedValueOnce(new Error('network'))
  await expect(store.addShot({ x: 20, y: 30 })).rejects.toThrow('network')
  expect(store.nodes.some(node => node.kind === 'shot')).toBe(false)
})
```

- [ ] **Step 2: Run and verify failures**

Run:

```bash
cd web
npm run test -- src/features/workbench/store/workbenchPersistence.test.ts src/features/workbench/store/workbenchStore.test.ts
```

- [ ] **Step 3: Implement v2 serialization**

Use:

```ts
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
```

Read `layout:v1`, normalize `mediaEdges` into `manualEdges`, and write to `layout:v2` only after a successful parse.

- [ ] **Step 4: Expand history and explicit-key operations**

Add selections, manual edges, and all manual node kinds to snapshots. Implement:

```ts
async deleteNodeKeys(keys: string[]) {
  const selected = [...new Set(keys)]
    .map(key => this.nodeByKey(key))
    .filter((node): node is WorkbenchNode => Boolean(node))
  const shots = selected.filter(node => node.kind === 'shot')
  const manualKeys = new Set(selected
    .filter(node => isManualNodeKind(node.kind))
    .map(node => node.key))

  await Promise.all(shots.map(node => api.deleteScene(node.id)))
  if (manualKeys.size) this.checkpoint()

  const shotKeys = new Set(shots.map(node => node.key))
  const removedKeys = new Set([...manualKeys, ...shotKeys])
  this.scenes = this.scenes.filter(scene => !shots.some(node => node.id === scene.id))
  this.manualNodes = this.manualNodes.filter(node => !manualKeys.has(node.key))
  this.manualNodes.filter(node => node.kind === 'section').forEach((section) => {
    const members = Array.isArray(section.data.node_keys)
      ? section.data.node_keys.filter((key): key is string => typeof key === 'string')
      : []
    section.data.node_keys = members.filter(key => !removedKeys.has(key))
  })
  this.manualEdges = this.manualEdges.filter(edge =>
    !removedKeys.has(edge.source) && !removedKeys.has(edge.target))
  this.clearSelection()
  this.rebuildGraph()
  this.persistLayout()
  return removedKeys.size
}

async deleteSelection() {
  return this.deleteNodeKeys([...this.selectedNodeKeys])
}
```

Change node-internal delete buttons to `store.deleteNodeKeys([props.id])`.

- [ ] **Step 5: Verify**

Run:

```bash
cd web
npm run test -- src/features/workbench/store/workbenchPersistence.test.ts src/features/workbench/store/workbenchStore.test.ts
npm run typecheck
```

In Chrome, delete a note from its node toolbar, undo, redo, copy/paste it, and confirm selection remains correct.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/workbench/store/workbenchPersistence.ts web/src/features/workbench/store/workbenchPersistence.test.ts web/src/features/workbench/store/workbenchStore.test.ts web/src/features/workbench/types/workbenchTypes.ts
git add -p web/src/features/workbench/store/workbenchStore.ts web/src/features/workbench/components/WorkbenchNodeFrame.vue web/src/features/workbench/nodes/NoteNode.vue
git commit -m "fix: make workbench edits recoverable"
```

### Task 7: Match the Top Identity, Toolbar, Add Menu, and Run CTA

**Files:**
- Create: `web/src/features/workbench/execution/workbenchCapabilities.ts`
- Test: `web/src/features/workbench/execution/workbenchCapabilities.test.ts`
- Create: `web/src/features/workbench/components/WorkbenchCanvasIdentity.vue`
- Test: `web/src/features/workbench/components/WorkbenchToolbar.spec.ts`
- Modify: `web/src/features/workbench/components/WorkbenchToolbar.vue`
- Modify: `web/src/features/workbench/pages/CreativeCanvas.vue`
- Modify: `web/src/features/workbench/styles/workbench.css`
- Modify: `web/src/pages/ShortDramaStoryboardPage.vue`

**Interfaces:**
- Produces: `selectedRunState(nodes, capabilities): { enabled; label; reason; runnableKeys }`
- Produces toolbar prop: `runState: WorkbenchRunState`
- Produces toolbar events: `addAsset`, `addShot`, `addNote`, `addWatermark`, `addComposer`, `uploadImage`, `uploadVideo`, `uploadAudio`, `addAudioReference`, `addDigitalHuman`

- [ ] **Step 1: Write CTA and menu tests**

```ts
import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import type { WorkbenchCapabilities } from '@/types'
import WorkbenchToolbar from '../components/WorkbenchToolbar.vue'
import { selectedRunState } from './workbenchCapabilities'

const capabilities: WorkbenchCapabilities = {
  upload_media: true,
  generate_asset: true,
  generate_video: true,
  apply_watermark: false,
  compose_video: false,
}

it('disables the CTA when selection is empty', () => {
  expect(selectedRunState([], capabilities)).toEqual({
    enabled: false,
    label: '请先选择可执行节点',
    reason: '请选择资产、镜头、水印或视频合成节点',
    runnableKeys: [],
  })
})

it('shows every verified add menu item in order', async () => {
  const wrapper = mount(WorkbenchToolbar, {
    props: {
      running: false,
      canUndo: false,
      canRedo: false,
      hasSelection: false,
      canCopy: false,
      canPaste: false,
      canCreateSection: false,
      runState: selectedRunState([], capabilities),
    },
  })
  await wrapper.get('[aria-label="添加节点"]').trigger('click')
  expect(wrapper.findAll('[role="menuitem"]').map(item => item.text())).toEqual([
    '空资产', '镜头', '便签', '水印', '视频合成',
    '上传图片', '上传视频', '上传音频', '参考音频', '数字人',
  ])
})
```

- [ ] **Step 2: Run and verify failures**

Run:

```bash
cd web
npm run test -- src/features/workbench/execution/workbenchCapabilities.test.ts src/features/workbench/components/WorkbenchToolbar.spec.ts
```

- [ ] **Step 3: Implement run eligibility**

Map node kinds to required capability keys. Ignored nodes and nodes missing required fields are not runnable. Return the exact disabled reason for the first invalid selected node.

```ts
export interface WorkbenchRunState {
  enabled: boolean
  label: '请先选择可执行节点' | '运行所选配置'
  reason: string
  runnableKeys: string[]
}

export function selectedRunState(
  nodes: WorkbenchNode[],
  capabilities: WorkbenchCapabilities,
): WorkbenchRunState
```

- [ ] **Step 4: Implement editable identity**

`WorkbenchCanvasIdentity.vue` accepts:

```ts
defineProps<{ name: string; chapterNumber: number; saving?: boolean }>()
defineEmits<{ rename: [name: string] }>()
```

Save trimmed changes through `api.updateChapter`; restore the server name on failure.

- [ ] **Step 5: Rebuild the add menu and CTA**

Use the exact menu order from the test, 34px buttons, tooltip copy with shortcuts, and:

```vue
<AppButton
  class="workbench-toolbar__button--primary"
  :disabled="!runState.enabled || running"
  :title="runState.enabled ? '运行所选配置' : runState.reason"
  @click="$emit('runSelected')"
>
  <Play :size="16" />
  <span>{{ running ? '运行中' : runState.label }}</span>
</AppButton>
```

- [ ] **Step 6: Verify**

Run:

```bash
cd web
npm run test -- src/features/workbench/execution/workbenchCapabilities.test.ts src/features/workbench/components/WorkbenchToolbar.spec.ts
npm run typecheck
```

Chrome-check menu order, Escape/focus restoration, shortcut tooltips, empty CTA, runnable-shot CTA, and story/workflow switch.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/workbench/execution web/src/features/workbench/components/WorkbenchCanvasIdentity.vue web/src/features/workbench/components/WorkbenchToolbar.spec.ts
git add -p web/src/features/workbench/components/WorkbenchToolbar.vue web/src/features/workbench/pages/CreativeCanvas.vue web/src/features/workbench/styles/workbench.css web/src/pages/ShortDramaStoryboardPage.vue
git commit -m "feat: align workbench chrome and toolbar"
```

### Task 8: Add Reference-Equivalent Asset Configuration and Versions

**Files:**
- Create: `web/src/features/workbench/config/assetConfig.ts`
- Test: `web/src/features/workbench/config/assetConfig.test.ts`
- Modify: `web/src/features/workbench/nodes/AssetNode.vue`
- Modify: `web/src/features/workbench/store/workbenchStore.ts`
- Modify: `web/src/features/workbench/styles/workbench.css`

**Interfaces:**
- Produces: `normalizeAssetConfig(asset): AssetWorkbenchConfig`
- Produces: `assetImageCandidates(asset): AssetImageCandidate[]`
- Produces: `store.addEmptyAsset(position)`
- Produces: `store.setAssetMainImage(assetId, url)`

- [ ] **Step 1: Write metadata and candidate tests**

```ts
import { expect, it } from 'vitest'
import type { Asset } from '@/types'
import { AssetTypeEnum } from '@/types'
import { assetImageCandidates, normalizeAssetConfig } from './assetConfig'

function makeAsset(patch: Partial<Asset> = {}): Asset {
  return {
    id: 1,
    novel_id: 9,
    asset_type: AssetTypeEnum.PERSON,
    canonical_name: '角色',
    created_at: '2026-07-25T00:00:00.000Z',
    updated_at: '2026-07-25T00:00:00.000Z',
    ...patch,
  }
}

it('normalizes missing asset settings to Shengshi defaults', () => {
  expect(normalizeAssetConfig(makeAsset({ metadata: undefined }))).toMatchObject({
    generationCount: 1,
    resolution: '1K',
    format: 'PNG',
    digitalHumanAssetId: '',
  })
})

it('deduplicates the three real image fields', () => {
  const asset = makeAsset({
    main_image: '/a.png',
    angle_image_1: '/a.png',
    angle_image_2: '/b.png',
  })
  expect(assetImageCandidates(asset).map(item => item.url)).toEqual(['/a.png', '/b.png'])
})
```

- [ ] **Step 2: Run and verify failures**

Run: `cd web && npm run test -- src/features/workbench/config/assetConfig.test.ts`

- [ ] **Step 3: Implement config normalization**

Persist:

```ts
export interface AssetWorkbenchConfig {
  generationCount: 1 | 2 | 3 | 4
  resolution: '1K' | '2K'
  format: 'PNG'
  digitalHumanAssetId: string
}
```

Read/write these values under `asset.metadata.workbench`.

- [ ] **Step 4: Add Store actions**

`addEmptyAsset(position)` calls `api.createAsset` with a unique `资产 N`, current `novel_id`, type `PERSON`, then rebuilds, positions, selects, and persists the node. `setAssetMainImage` patches the real `main_image`.

- [ ] **Step 5: Rebuild the node controls**

Add:

- type selector with five exact labels;
- nickname input;
- person-only digital-human picker;
- generation count;
- 1K/2K;
- PNG;
- candidate thumbnails;
- selected main-image radio action;
- prompt editor;
- real save/generate states.

Disable generation for product/style when the backend generator does not advertise support, and show that reason in the button title.

- [ ] **Step 6: Verify**

Run:

```bash
cd web
npm run test -- src/features/workbench/config/assetConfig.test.ts
npm run typecheck
```

Chrome-check every selector, candidate switch, and main version restoration without triggering generation.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/workbench/config/assetConfig.ts web/src/features/workbench/config/assetConfig.test.ts web/src/features/workbench/nodes/AssetNode.vue
git add -p web/src/features/workbench/store/workbenchStore.ts web/src/features/workbench/styles/workbench.css
git commit -m "feat: align asset node configuration"
```

### Task 9: Add Reference-Equivalent Shot Configuration and Video Versions

**Files:**
- Create: `web/src/features/workbench/config/shotConfig.ts`
- Test: `web/src/features/workbench/config/shotConfig.test.ts`
- Modify: `web/src/features/workbench/nodes/ShotNode.vue`
- Modify: `web/src/features/workbench/store/workbenchStore.ts`
- Modify: `web/src/features/workbench/styles/workbench.css`

**Interfaces:**
- Produces: `normalizeShotConfig(scene, projectDefaults): ShotWorkbenchConfig`
- Produces: `store.setActiveVideo(sceneId, videoId)`
- Keeps `ShotNode.vue` warning-free with one DOM root.

- [ ] **Step 1: Write normalization tests**

```ts
import { expect, it } from 'vitest'
import type { Scene } from '@/types'
import { normalizeShotConfig } from './shotConfig'

const projectDefaults = { aspectRatio: '9:16' as const, resolution: '720p' as const }

function makeScene(patch: Partial<Scene> = {}): Scene {
  return {
    id: 10,
    chapter_id: 2162,
    sequence: 1,
    description: '镜头',
    prompt: '',
    duration: 6,
    created_at: '2026-07-25T00:00:00.000Z',
    updated_at: '2026-07-25T00:00:00.000Z',
    ...patch,
  }
}

it('uses verified shot defaults', () => {
  expect(normalizeShotConfig(makeScene(), projectDefaults)).toMatchObject({
    duration: 6,
    aspectRatio: '9:16',
    resolution: '720p',
    useLastFrame: false,
    referenceMode: 'prompt',
  })
})

it('clamps duration to one through thirty seconds', () => {
  expect(normalizeShotConfig(makeScene({ duration: 50 }), projectDefaults).duration).toBe(30)
})
```

- [ ] **Step 2: Run and verify failures**

Run: `cd web && npm run test -- src/features/workbench/config/shotConfig.test.ts`

- [ ] **Step 3: Define persisted shot config**

```ts
export interface ShotWorkbenchConfig {
  duration: number
  aspectRatio: '16:9' | '9:16' | '1:1' | '4:3' | '3:4'
  resolution: '480p' | '720p' | '1080p'
  useLastFrame: boolean
  referenceMode: 'prompt' | 'image'
  firstFrameUrl: string
  lastFrameUrl: string
  activeVideoId: number | null
  modelType: number | null
}
```

Store these values in `scene.metadata.workbench`; continue sending `duration` through the top-level scene field.

- [ ] **Step 4: Rebuild `ShotNode.vue`**

Render one root element containing:

- description and prompt;
- duration range plus number;
- ratio and resolution selects;
- tail-frame switch;
- collapsible asset reference list;
- prompt/image usage selector;
- model selector;
- real video-version selector;
- save, save-and-generate, and “运行此配置”.

Ensure the prompt editor Teleport is inside the one root so Vue no longer forwards listeners to a fragment.

- [ ] **Step 5: Wire active video and generation options**

`setActiveVideo` changes `activeVideoId` only. `generateVideo` uses:

```ts
{
  generation_mode: config.useLastFrame ? 'keyframes' : 'reference',
  first_frame_url: config.firstFrameUrl || undefined,
  last_frame_url: config.useLastFrame ? config.lastFrameUrl || undefined : undefined,
}
```

- [ ] **Step 6: Verify**

Run:

```bash
cd web
npm run test -- src/features/workbench/config/shotConfig.test.ts
npm run typecheck
```

Chrome-check duration `5 → 6 → 5`, all ratios, all resolutions, tail-frame toggle, usage modes, and video versions. Confirm zero fragment-listener warnings.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/workbench/config/shotConfig.ts web/src/features/workbench/config/shotConfig.test.ts web/src/features/workbench/nodes/ShotNode.vue
git add -p web/src/features/workbench/store/workbenchStore.ts web/src/features/workbench/styles/workbench.css
git commit -m "feat: align shot node configuration"
```

### Task 10: Add Uploaded Image, Video, and Audio Nodes

**Files:**
- Create: `web/src/features/workbench/nodes/ImageMediaNode.vue`
- Create: `web/src/features/workbench/nodes/VideoMediaNode.vue`
- Create: `web/src/features/workbench/nodes/AudioMediaNode.vue`
- Test: `web/src/features/workbench/store/workbenchMediaUpload.test.ts`
- Modify: `web/src/features/workbench/types/workbenchTypes.ts`
- Modify: `web/src/features/workbench/store/workbenchStore.ts`
- Modify: `web/src/features/workbench/pages/CreativeCanvas.vue`
- Modify: `web/src/features/workbench/styles/workbench.css`

**Interfaces:**
- Adds kinds: `image_media`, `video_media`, `audio_media`
- Produces: `store.uploadMedia(kind, file, position): Promise<WorkbenchNode>`

- [ ] **Step 1: Write upload-state tests**

```ts
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { useWorkbenchStore } from './workbenchStore'

vi.mock('@/api', () => ({
  api: { upload: vi.fn() },
  sleep: vi.fn(),
}))

const uploadMock = vi.mocked(api.upload)
let store: ReturnType<typeof useWorkbenchStore>

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkbenchStore()
  store.chapterId = 2162
})

function imageFile() {
  return new File([new Uint8Array([137, 80, 78, 71])], 'photo.png', { type: 'image/png' })
}

function videoFile() {
  return new File([new Uint8Array([0, 0, 0, 24])], 'clip.mp4', { type: 'video/mp4' })
}

it('adds and selects a media node only after upload succeeds', async () => {
  uploadMock.mockResolvedValue({
    filename: 'photo.png',
    original_filename: 'photo.png',
    content_type: 'image/png',
    file_path: '/tmp/photo.png',
  })
  const node = await store.uploadMedia('image_media', imageFile(), { x: 50, y: 60 })
  expect(node.position).toEqual({ x: 50, y: 60 })
  expect(node.data.url).toBe('/media/photo.png')
  expect(store.selectedNodeKeys).toEqual([node.key])
})

it('leaves no node when upload rejects', async () => {
  uploadMock.mockRejectedValue(new Error('too large'))
  await expect(store.uploadMedia('video_media', videoFile(), { x: 0, y: 0 }))
    .rejects.toThrow('too large')
  expect(store.nodes.some(node => node.kind === 'video_media')).toBe(false)
})
```

- [ ] **Step 2: Run and verify failures**

Run: `cd web && npm run test -- src/features/workbench/store/workbenchMediaUpload.test.ts`

- [ ] **Step 3: Implement media data and Store action**

```ts
export type ImageAnnotationTool = 'rectangle' | 'ellipse' | 'grid' | 'arrow' | 'freehand'

export interface ImageAnnotation {
  id: string
  tool: ImageAnnotationTool
  points: Point[]
  stroke: string
  strokeWidth: number
}

export interface UploadedMediaData {
  url: string
  filename: string
  originalFilename: string
  mimeType: string
  width?: number
  height?: number
  durationSeconds?: number
  annotations?: ImageAnnotation[]
}
```

Validate MIME before upload, call the real file endpoint, then create the persistent manual node.

- [ ] **Step 4: Add hidden inputs and node renderers**

Use exact accepts:

```html
image/png,image/jpeg,image/webp
video/mp4,video/webm,video/quicktime
audio/mpeg,audio/wav,audio/mp4,audio/webm
```

Register the three node components and use existing `WorkbenchVideoMedia` and `WorkbenchAudioMedia`.

- [ ] **Step 5: Verify**

Run:

```bash
cd web
npm run test -- src/features/workbench/store/workbenchMediaUpload.test.ts
npm run typecheck
```

Chrome-check file chooser opening and cancel behavior. Use only a local disposable fixture for the successful upload check, then delete the created node.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/workbench/nodes/ImageMediaNode.vue web/src/features/workbench/nodes/VideoMediaNode.vue web/src/features/workbench/nodes/AudioMediaNode.vue web/src/features/workbench/store/workbenchMediaUpload.test.ts
git add -p web/src/features/workbench/types/workbenchTypes.ts web/src/features/workbench/store/workbenchStore.ts web/src/features/workbench/pages/CreativeCanvas.vue web/src/features/workbench/styles/workbench.css
git commit -m "feat: add workbench media uploads"
```

### Task 11: Add the Image Annotation Editor

**Files:**
- Create: `web/src/features/workbench/annotation/imageAnnotations.ts`
- Test: `web/src/features/workbench/annotation/imageAnnotations.test.ts`
- Create: `web/src/features/workbench/components/ImageAnnotationDialog.vue`
- Test: `web/src/features/workbench/components/ImageAnnotationDialog.spec.ts`
- Modify: `web/src/features/workbench/nodes/ImageMediaNode.vue`
- Modify: `web/src/features/workbench/store/workbenchStore.ts`
- Modify: `web/src/features/workbench/styles/workbench.css`

**Interfaces:**
- Consumes: `ImageAnnotation` and `ImageAnnotationTool` from `workbenchTypes.ts`
- Produces editor tool: `AnnotationEditorTool = 'move' | ImageAnnotationTool`
- Produces: `normalizeImagePoint(clientPoint, imageBounds): NormalizedPoint`
- Produces: `emptyAnnotationState(): AnnotationState`
- Produces: `annotationReducer(state, action): AnnotationState`

- [ ] **Step 1: Write geometry and history tests**

```ts
import { expect, it } from 'vitest'
import type { ImageAnnotation } from '../types/workbenchTypes'
import {
  annotationReducer,
  emptyAnnotationState,
  normalizeImagePoint,
} from './imageAnnotations'

const rect: ImageAnnotation = {
  id: 'rect-1',
  tool: 'rectangle',
  points: [{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 }],
  stroke: '#ff5a5f',
  strokeWidth: 3,
}
const arrow: ImageAnnotation = {
  id: 'arrow-1',
  tool: 'arrow',
  points: [{ x: 0.2, y: 0.2 }, { x: 0.8, y: 0.8 }],
  stroke: '#ff5a5f',
  strokeWidth: 3,
}

it('normalizes points within zero and one', () => {
  expect(normalizeImagePoint(
    { x: 150, y: 100 },
    { left: 100, top: 50, width: 200, height: 100 },
  )).toEqual({ x: 0.25, y: 0.5 })
})

it('undoes the last shape and clear is itself undoable', () => {
  const withOne = annotationReducer(emptyAnnotationState(), { type: 'add', shape: rect })
  const withTwo = annotationReducer(withOne, { type: 'add', shape: arrow })
  expect(annotationReducer(withTwo, { type: 'undo' }).shapes).toEqual([rect])
  const cleared = annotationReducer(withTwo, { type: 'clear' })
  expect(annotationReducer(cleared, { type: 'undo' }).shapes).toEqual([rect, arrow])
})
```

- [ ] **Step 2: Run and verify failures**

Run:

```bash
cd web
npm run test -- src/features/workbench/annotation/imageAnnotations.test.ts
```

- [ ] **Step 3: Implement normalized annotation state**

Store all points in `[0, 1]`, clamp pointer input, and model clear/undo with immutable history snapshots.

- [ ] **Step 4: Build the dialog**

Render six exact tools, brush slider, zoom in/out/reset, undo, clear, cancel, and save. Draw annotations in an SVG overlay so saved normalized coordinates remain responsive.

- [ ] **Step 5: Add component behavior tests**

```ts
import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import ImageAnnotationDialog from './ImageAnnotationDialog.vue'

it('offers the six reference tools and keeps save explicit', async () => {
  const wrapper = mount(ImageAnnotationDialog, {
    attachTo: document.body,
    props: {
      open: true,
      imageUrl: '/media/photo.png',
      modelValue: [],
    },
  })
  expect(wrapper.get('[aria-label="批注工具"]').findAll('button').map(button => button.attributes('aria-label')))
    .toEqual(['移动', '矩形', '椭圆', '网格', '箭头', '涂鸦'])
  await wrapper.get('[aria-label="清空批注"]').trigger('click')
  await wrapper.get('[aria-label="撤销批注操作"]').trigger('click')
  expect(wrapper.emitted('save')).toBeUndefined()
})
```

- [ ] **Step 6: Verify**

Run:

```bash
cd web
npm run test -- src/features/workbench/annotation/imageAnnotations.test.ts src/features/workbench/components/ImageAnnotationDialog.spec.ts
npm run typecheck
```

Chrome-check all tools with a disposable uploaded image, save locally, reopen, and remove the image node.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/workbench/annotation web/src/features/workbench/components/ImageAnnotationDialog.vue web/src/features/workbench/components/ImageAnnotationDialog.spec.ts
git add -p web/src/features/workbench/nodes/ImageMediaNode.vue web/src/features/workbench/store/workbenchStore.ts web/src/features/workbench/styles/workbench.css
git commit -m "feat: add image annotation tooling"
```

### Task 12: Add Watermark Configuration with Honest Execution State

**Files:**
- Create: `web/src/features/workbench/config/watermarkConfig.ts`
- Test: `web/src/features/workbench/config/watermarkConfig.test.ts`
- Create: `web/src/features/workbench/components/WatermarkSettingsDialog.vue`
- Create: `web/src/features/workbench/nodes/WatermarkNode.vue`
- Modify: `web/src/features/workbench/store/workbenchStore.ts`
- Modify: `web/src/features/workbench/pages/CreativeCanvas.vue`
- Modify: `web/src/features/workbench/components/WorkbenchNodeFrame.vue`
- Modify: `web/src/features/workbench/styles/workbench.css`

**Interfaces:**
- Adds kind: `watermark`
- Produces: `WatermarkPreset = 'top-left' | 'top' | 'top-right' | 'left' | 'center' | 'right' | 'bottom-left' | 'bottom' | 'bottom-right'`
- Produces: `watermarkPreset(name): { x: number; y: number }`
- Produces: `store.addWatermark(position)`
- Produces source handle: `watermark-output`

- [ ] **Step 1: Write preset tests**

```ts
import { expect, it } from 'vitest'
import type { WatermarkPreset } from './watermarkConfig'
import { watermarkPreset } from './watermarkConfig'

it.each([
  ['top-left', { x: 0.08, y: 0.08 }],
  ['center', { x: 0.5, y: 0.5 }],
  ['bottom-right', { x: 0.92, y: 0.92 }],
])('maps %s to normalized coordinates', (name, expected) => {
  expect(watermarkPreset(name as WatermarkPreset)).toEqual(expected)
})
```

- [ ] **Step 2: Run and verify failure**

Run: `cd web && npm run test -- src/features/workbench/config/watermarkConfig.test.ts`

- [ ] **Step 3: Implement configuration**

```ts
export interface WatermarkConfig {
  resourceUrl: string
  x: number
  y: number
  scale: number
  opacity: number
}
```

Clamp X/Y/scale/opacity, expose nine presets, and checkpoint only once per completed slider interaction.

- [ ] **Step 4: Build the node and settings dialog**

The node accepts video-result/video-media input, previews the watermark, and exposes `watermark-output`. The run button uses backend capabilities:

```ts
const disabledReason = capabilities.apply_watermark
  ? missingInputReason.value
  : '当前服务未启用水印执行'
```

No output node is created while capability is false.

- [ ] **Step 5: Verify**

Run:

```bash
cd web
npm run test -- src/features/workbench/config/watermarkConfig.test.ts
npm run typecheck
```

Chrome-check nine presets, X/Y/scale/opacity, undo/redo, and the truthful disabled run reason.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/workbench/config/watermarkConfig.ts web/src/features/workbench/config/watermarkConfig.test.ts web/src/features/workbench/components/WatermarkSettingsDialog.vue web/src/features/workbench/nodes/WatermarkNode.vue
git add -p web/src/features/workbench/store/workbenchStore.ts web/src/features/workbench/pages/CreativeCanvas.vue web/src/features/workbench/components/WorkbenchNodeFrame.vue web/src/features/workbench/styles/workbench.css
git commit -m "feat: add watermark canvas node"
```

### Task 13: Add Ordered Video Composition with Honest Execution State

**Files:**
- Create: `web/src/features/workbench/config/composerConfig.ts`
- Test: `web/src/features/workbench/config/composerConfig.test.ts`
- Create: `web/src/features/workbench/nodes/VideoComposerNode.vue`
- Modify: `web/src/features/workbench/store/workbenchStore.ts`
- Modify: `web/src/features/workbench/pages/CreativeCanvas.vue`
- Modify: `web/src/features/workbench/styles/workbench.css`

**Interfaces:**
- Adds kind: `video_composer`
- Produces: `orderedComposerInputs(nodeKey, nodes, edges): ComposerInput[]`
- Produces: `store.moveComposerInput(composerKey, inputKey, direction)`

- [ ] **Step 1: Write ordering tests**

```ts
import { expect, it } from 'vitest'
import type { WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import { moveOrder, orderedComposerInputs } from './composerConfig'

const timestamp = '2026-07-25T00:00:00.000Z'
const nodes = ['video-1', 'video-2'].map((key, index) => ({
  id: index + 1,
  key,
  kind: 'video_result',
  backendKind: 'video_result',
  title: key,
  position: { x: 0, y: 0 },
  size: null,
  zIndex: 1,
  activeVersionId: null,
  status: 'ready',
  data: {
    video: {
      id: index + 1,
      scene_id: index + 1,
      model_type: 1,
      status: 3,
      created_at: timestamp,
      updated_at: timestamp,
    },
    ui: {},
  },
  createdAt: timestamp,
  updatedAt: timestamp,
})) as WorkbenchNode[]

function composerEdge(source: string, target: string, orderIndex: number): WorkbenchEdge {
  return {
    id: orderIndex + 1,
    key: `${source}-${target}`,
    source,
    target,
    type: 'output_binding',
    backendType: 'output_binding',
    sourceHandle: null,
    targetHandle: null,
    orderIndex,
    config: null,
    createdAt: timestamp,
    updatedAt: timestamp,
  }
}

it('orders connected videos by explicit edge orderIndex', () => {
  const result = orderedComposerInputs('composer-1', nodes, [
    composerEdge('video-2', 'composer-1', 1),
    composerEdge('video-1', 'composer-1', 0),
  ])
  expect(result.map(item => item.key)).toEqual(['video-1', 'video-2'])
})

it('moves one clip and reindexes every edge', () => {
  expect(moveOrder(['a', 'b', 'c'], 'b', 'up')).toEqual(['b', 'a', 'c'])
  expect(moveOrder(['a', 'b', 'c'], 'b', 'down')).toEqual(['a', 'c', 'b'])
})
```

- [ ] **Step 2: Run and verify failures**

Run: `cd web && npm run test -- src/features/workbench/config/composerConfig.test.ts`

- [ ] **Step 3: Implement deterministic ordering**

Sort by `orderIndex`, then stable key. Moving a clip rewrites every related edge to sequential indexes `0..n-1` in one history checkpoint.

```ts
export interface ComposerInput {
  key: string
  title: string
  url: string
  durationSeconds: number
  orderIndex: number
}

export type ComposerMoveDirection = 'up' | 'down'
```

- [ ] **Step 4: Build the composer node**

Render ordered video titles, move up/down, remove, ratio, resolution, duration total, and compose/preview CTA. When `compose_video` is false, disable it with `当前服务未启用视频合成`.

- [ ] **Step 5: Verify**

Run:

```bash
cd web
npm run test -- src/features/workbench/config/composerConfig.test.ts
npm run typecheck
```

Chrome-check original order, up/down restoration, all output choices, and disabled execution reason without submitting a compose request.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/workbench/config/composerConfig.ts web/src/features/workbench/config/composerConfig.test.ts web/src/features/workbench/nodes/VideoComposerNode.vue
git add -p web/src/features/workbench/store/workbenchStore.ts web/src/features/workbench/pages/CreativeCanvas.vue web/src/features/workbench/styles/workbench.css
git commit -m "feat: add video composer node"
```

### Task 14: Fix Resource Search Reset and Complete Node Action Integration

**Files:**
- Test: `web/src/features/workbench/components/MediaLibraryPicker.spec.ts`
- Modify: `web/src/features/workbench/components/MediaLibraryPicker.vue`
- Test: `web/src/features/workbench/components/WorkbenchNodeFrame.spec.ts`
- Modify: `web/src/features/workbench/components/WorkbenchNodeFrame.vue`
- Modify: `web/src/features/workbench/pages/CreativeCanvas.vue`
- Modify: `web/src/features/workbench/store/workbenchStore.ts`
- Modify: `web/src/features/workbench/styles/workbench.css`

**Interfaces:**
- Produces monotonic request id handling for media search.
- Produces one capability table for delete/copy/run/connect behavior by node kind.

- [ ] **Step 1: Write the search reset regression**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { api } from '@/api'
import type { AudioReference, PaginationResponse } from '@/types'
import MediaLibraryPicker from './MediaLibraryPicker.vue'

vi.mock('@/api', () => ({
  api: {
    audioReferences: vi.fn(),
    digitalHumans: vi.fn(),
  },
}))

const audioReferencesMock = vi.mocked(api.audioReferences)
const audioItem = (asset_id: string): AudioReference => ({
  id: Number(asset_id === 'one' ? 1 : 2),
  nickname: asset_id,
  gender: '女',
  audio_url: `/media/${asset_id}.mp3`,
  avatar_url: `/media/${asset_id}.png`,
  asset_id,
  is_active: true,
  created_at: '2026-07-25T00:00:00.000Z',
  updated_at: '2026-07-25T00:00:00.000Z',
})
const pageOf = (assetIds: string[]): PaginationResponse<AudioReference> => ({
  code: 0,
  message: 'ok',
  data: {
    items: assetIds.map(audioItem),
    pagination: { total: assetIds.length, page: 1, page_size: 24, pages: 1 },
  },
})

it('reloads the full first page after clearing search', async () => {
  audioReferencesMock
    .mockResolvedValueOnce(pageOf(['one']))
    .mockResolvedValueOnce(pageOf(['one']))
    .mockResolvedValueOnce(pageOf(['one', 'two']))
  const wrapper = mount(MediaLibraryPicker, { props: { open: true, kind: 'audio' } })
  await flushPromises()
  await wrapper.get('input').setValue('one')
  await wrapper.get('form').trigger('submit')
  await wrapper.get('input').setValue('')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.findAll('.media-picker-grid > button')).toHaveLength(2)
})
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
cd web
npm run test -- src/features/workbench/components/MediaLibraryPicker.spec.ts
```

- [ ] **Step 3: Fix request serialization**

Increment `requestId` for every load, allow reset calls while an earlier request is pending, and apply a response only when its captured id equals the latest id. Reset page/items before issuing the request.

- [ ] **Step 4: Centralize node capability behavior**

Define:

```ts
const NODE_CAPABILITIES: Record<WorkbenchNodeKind, {
  deletable: boolean
  copyable: boolean
  runnable: boolean
  target: boolean
  source: boolean
}> = {
  chapter: { deletable: false, copyable: false, runnable: false, target: false, source: true },
  asset: { deletable: true, copyable: false, runnable: true, target: false, source: true },
  audio_reference: { deletable: true, copyable: false, runnable: false, target: false, source: true },
  digital_human: { deletable: true, copyable: false, runnable: false, target: false, source: true },
  shot: { deletable: true, copyable: true, runnable: true, target: true, source: true },
  video_result: { deletable: true, copyable: false, runnable: false, target: true, source: true },
  image_media: { deletable: true, copyable: false, runnable: false, target: false, source: true },
  video_media: { deletable: true, copyable: false, runnable: false, target: false, source: true },
  audio_media: { deletable: true, copyable: false, runnable: false, target: false, source: true },
  watermark: { deletable: true, copyable: false, runnable: true, target: true, source: true },
  video_composer: { deletable: true, copyable: false, runnable: true, target: true, source: false },
  section: { deletable: true, copyable: false, runnable: false, target: false, source: false },
  note: { deletable: true, copyable: true, runnable: false, target: false, source: false },
  unsupported: { deletable: false, copyable: false, runnable: false, target: false, source: false },
}
```

Use it in `WorkbenchNodeFrame`, toolbar computed states, connection validation, and keyboard deletion.

- [ ] **Step 5: Verify**

Run:

```bash
cd web
npm run test -- src/features/workbench/components/MediaLibraryPicker.spec.ts src/features/workbench/components/WorkbenchNodeFrame.spec.ts
npm run typecheck
npm run build
```

Expected: all pass and TypeScript enforces exhaustive node kinds.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/workbench/components/MediaLibraryPicker.spec.ts web/src/features/workbench/components/WorkbenchNodeFrame.spec.ts
git add -p web/src/features/workbench/components/MediaLibraryPicker.vue web/src/features/workbench/components/WorkbenchNodeFrame.vue web/src/features/workbench/pages/CreativeCanvas.vue web/src/features/workbench/store/workbenchStore.ts web/src/features/workbench/styles/workbench.css
git commit -m "fix: finish workbench action integration"
```

### Task 15: Make Loading, Polling, and Unmount Concurrency Safe

**Files:**
- Create: `web/src/features/workbench/execution/workbenchAsync.ts`
- Test: `web/src/features/workbench/execution/workbenchAsync.test.ts`
- Test: `web/src/features/workbench/store/workbenchConcurrency.test.ts`
- Modify: `web/src/features/workbench/store/workbenchStore.ts`
- Modify: `web/src/features/workbench/pages/CreativeCanvas.vue`

**Interfaces:**
- Produces: `pollUntilTerminal(fetchState, options): Promise<TerminalTask>`
- Produces: `WorkbenchLoadEpoch` with `begin()` and `isCurrent(epoch)`.
- Produces: `store.cancelPendingWork()`.

- [ ] **Step 1: Write abort and late-load tests**

```ts
import { expect, it, vi } from 'vitest'
import { pollUntilTerminal, WorkbenchLoadEpoch } from './workbenchAsync'

it('stops polling immediately after abort', async () => {
  const controller = new AbortController()
  const fetchState = vi.fn().mockResolvedValue({ status: 2 })
  controller.abort()
  await expect(pollUntilTerminal(fetchState, {
    signal: controller.signal,
    intervalMs: 1,
    terminalStatuses: new Set([3, 4, 5]),
  })).rejects.toMatchObject({ name: 'AbortError' })
  expect(fetchState).not.toHaveBeenCalled()
})

it('marks an earlier chapter load as stale', () => {
  const epochs = new WorkbenchLoadEpoch()
  const first = epochs.begin()
  const second = epochs.begin()
  expect(epochs.isCurrent(first)).toBe(false)
  expect(epochs.isCurrent(second)).toBe(true)
})
```

In `workbenchConcurrency.test.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia'
import { expect, it, vi } from 'vitest'
import { api } from '@/api'
import type { Chapter, SingleResponse } from '@/types'
import { useWorkbenchStore } from './workbenchStore'

vi.mock('@/api', () => ({
  api: {
    chapter: vi.fn(),
    assets: vi.fn().mockResolvedValue({
      data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } },
    }),
    scenes: vi.fn().mockResolvedValue({
      data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } },
    }),
    enums: vi.fn().mockResolvedValue({ data: { video_model_type: [] } }),
  },
  sleep: vi.fn(),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

function chapter(id: number, name: string): Chapter {
  return {
    id,
    novel_id: 9,
    number: id,
    name,
    created_at: '2026-07-25T00:00:00.000Z',
    updated_at: '2026-07-25T00:00:00.000Z',
  }
}

it('ignores a chapter load that resolves after a newer load', async () => {
  setActivePinia(createPinia())
  const store = useWorkbenchStore()
  const first = deferred<SingleResponse<Chapter>>()
  const second = deferred<SingleResponse<Chapter>>()
  vi.mocked(api.chapter)
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise)

  const loadingFirst = store.load(9, 1)
  const loadingSecond = store.load(9, 2)
  second.resolve({ code: 0, message: 'ok', data: chapter(2, '第二章') })
  await loadingSecond
  first.resolve({ code: 0, message: 'ok', data: chapter(1, '第一章') })
  await loadingFirst

  expect(store.chapter?.id).toBe(2)
  expect(store.nodes[0]?.title).toContain('第二章')
})
```

- [ ] **Step 2: Run and verify failures**

Run:

```bash
cd web
npm run test -- src/features/workbench/execution/workbenchAsync.test.ts src/features/workbench/store/workbenchConcurrency.test.ts
```

- [ ] **Step 3: Implement abortable polling**

```ts
export async function pollUntilTerminal<T extends { status: number }>(
  fetchState: () => Promise<T>,
  options: {
    signal: AbortSignal
    intervalMs: number
    terminalStatuses: ReadonlySet<number>
  },
): Promise<T> {
  while (true) {
    if (options.signal.aborted) throw new DOMException('Aborted', 'AbortError')
    const state = await fetchState()
    if (options.terminalStatuses.has(state.status)) return state
    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(resolve, options.intervalMs)
      options.signal.addEventListener('abort', () => {
        window.clearTimeout(timeout)
        reject(new DOMException('Aborted', 'AbortError'))
      }, { once: true })
    })
  }
}

export class WorkbenchLoadEpoch {
  private value = 0
  begin() { this.value += 1; return this.value }
  isCurrent(epoch: number) { return epoch === this.value }
}
```

- [ ] **Step 4: Apply lifecycle ownership in the Store**

Keep one load epoch and per-run `AbortController`. Before committing load results, assert the epoch is current. `cancelPendingWork()` aborts every active controller, clears only running indicators owned by those controllers, and does not erase successful nodes.

In `CreativeCanvas.vue`, call `store.cancelPendingWork()` from `onBeforeUnmount`.

- [ ] **Step 5: Verify**

Run:

```bash
cd web
npm run test -- src/features/workbench/execution/workbenchAsync.test.ts src/features/workbench/store/workbenchConcurrency.test.ts
npm run typecheck
```

Navigate quickly between two chapter URLs and confirm the final canvas always matches the latest URL. Start only mocked polling in tests; do not submit a real generation.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/workbench/execution/workbenchAsync.ts web/src/features/workbench/execution/workbenchAsync.test.ts web/src/features/workbench/store/workbenchConcurrency.test.ts
git add -p web/src/features/workbench/store/workbenchStore.ts web/src/features/workbench/pages/CreativeCanvas.vue
git commit -m "fix: cancel stale workbench requests"
```

### Task 16: Full Verification and Button-by-Button Chrome Regression

**Files:**
- Modify: `docs/superpowers/specs/2026-07-25-wireless-canvas-parity-design.md` only if the verified contract changed.
- Create: `docs/superpowers/verification/2026-07-25-wireless-canvas-parity.md`

**Interfaces:**
- Produces an evidence table with reference state, local state, action, observed result, restore action, and final state.

- [ ] **Step 1: Run the full automated suite**

Run:

```bash
uv run pytest
cd web
npm run test
npm run typecheck
npm run build
```

Expected: all commands exit `0`.

- [ ] **Step 2: Verify desktop rendering at both required viewports**

Check `2555×1278` and `1280×720`. Record toolbar bounds, occlusion, canvas fit, multi-column layout, node card readability, prompt editor bounds, and dialog overflow.

- [ ] **Step 3: Run the reference/local button matrix**

For each group, record before/action/after/restore:

- return, identity, view switch, main run CTA;
- every add-menu item;
- select, pan, zoom in/out, fit, lock, auto-layout;
- undo, redo, copy, paste, delete, section;
- info, color, pin, collapse, ignore, node delete;
- asset types, nickname, digital human, count, size, format, candidates, main version;
- shot duration, ratio, resolution, tail frame, reference strategy, video versions;
- audio/digital-human search, clear, select, close;
- image annotation six tools, brush, zoom, reset, undo, clear;
- watermark presets and sliders;
- composer order, ratio, resolution, disabled execution.

- [ ] **Step 4: Inspect console and network evidence**

Confirm:

- no `Viewport not initialized yet`;
- no Vue fragment listener warning;
- no unhandled Promise rejection;
- no paid generation/composition/watermark request during regression;
- upload requests occur only for the explicitly chosen disposable fixture.

- [ ] **Step 5: Restore browser and backend state**

Delete disposable local nodes and uploaded fixture references, restore shot duration to `5`, ratio to `9:16`, resolution to `720p`, tail-frame off, original active versions, and composer order. Confirm no dialogs remain open.

- [ ] **Step 6: Write the verification record**

The document must include:

```md
| Control | Reference evidence | Local evidence | Restored |
| --- | --- | --- | --- |
| Fit view | all visible nodes fitted | all visible nodes fitted; no console error | yes |
```

Include exact test commands and exit status, final node counts, final configuration values, and screenshots for both viewports.

- [ ] **Step 7: Apply the verification-before-completion skill**

Read `superpowers:verification-before-completion`, rerun any command whose output is stale, and compare every acceptance criterion in the approved design against direct evidence.

- [ ] **Step 8: Commit verification evidence**

```bash
git add docs/superpowers/verification/2026-07-25-wireless-canvas-parity.md
git commit -m "docs: verify wireless canvas parity"
```
