# Manual Asset Generation Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make extracted character fields, selected chapter scope, task completion, and generated-image display remain consistent.

**Architecture:** Normalize character metadata once in the backend persistence service, preserve the active frontend scope through a focused refresh, and make successful reference tasks require a persisted image. Keep animation state inside the existing manual asset card and honor reduced-motion preferences.

**Tech Stack:** Python 3.12, FastAPI/Tortoise, pytest, Vue 3, TypeScript, Vitest.

---

### Task 1: Deterministic character metadata

**Files:**
- Modify: `services/extraction/persistence.py`
- Test: `test/test_services/test_extraction_persistence.py`

- [ ] Add failing tests that save single-character extraction results containing Chinese, English, and numeric gender/age values and assert normalized metadata.
- [ ] Run `uv run pytest test/test_services/test_extraction_persistence.py -q` and confirm the new assertions fail because only `reference_layout` is stored.
- [ ] Add focused parsing helpers for fixed trait lines, gender aliases, age labels, and numeric ranges. Merge derived fields only when the incoming visual description is current.
- [ ] Re-run the persistence test file and confirm it passes.

### Task 2: Honest reference-image task completion

**Files:**
- Modify: `services/reference/handler.py`
- Create: `test/test_services/test_reference_handler.py`

- [ ] Add failing async tests for an empty generated list, all downloads failing, and one successfully persisted image.
- [ ] Run `uv run pytest test/test_services/test_reference_handler.py -q` and confirm empty/all-failed cases currently return `{"images": []}`.
- [ ] Enable redirect following in the downloader and raise a stable failure when no image URL is persisted; keep partial successes valid.
- [ ] Re-run the handler tests and confirm they pass.

### Task 3: Scope-preserving frontend refresh

**Files:**
- Modify: `web/src/pages/ShortDramaManualPage.vue`
- Modify: `web/src/pages/ShortDramaManualAssetScope.spec.ts`

- [ ] Add failing tests that enter current-chapter scope, invoke toolbar refresh and finish a batch, then assert every follow-up asset request includes the selected chapter ID.
- [ ] Run `cd web && npm run test -- src/pages/ShortDramaManualAssetScope.spec.ts` and confirm `loadProject()` causes an unfiltered request.
- [ ] Replace post-batch and toolbar full project reloads with `refreshAssets()` while retaining initial `loadProject()` behavior.
- [ ] Re-run the focused frontend test and confirm it passes.

### Task 4: Generating-card animation

**Files:**
- Modify: `web/src/pages/ShortDramaManualPage.vue`
- Create: `web/src/pages/ShortDramaManualGenerationState.test.mjs`

- [ ] Add a failing source/component test for the centered generating label, animated media class, and reduced-motion override.
- [ ] Run `cd web && npm run test -- src/pages/ShortDramaManualGenerationState.test.mjs` and confirm the expected state markup is absent.
- [ ] Add the in-card spinner/label, shimmer and count pulse, plus a `prefers-reduced-motion` override.
- [ ] Re-run the focused test and confirm it passes.

### Task 5: Verification

**Files:**
- Verify all modified files.

- [ ] Run the focused backend and frontend tests.
- [ ] Run `cd web && npm run typecheck`.
- [ ] Run `cd web && npm run build`.
- [ ] Run `git diff --check` and inspect `git diff --` for only in-scope changes.

Commits are intentionally omitted because the user requested implementation but did not request staging or committing.
