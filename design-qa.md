# Episode Applicability Picker QA

- Source visual truth: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-aa720c03-3499-4df0-a217-225cb8856aa4.png`
- Route: `http://localhost:3000/#/create/short-drama/manual/9?chapter=1107`
- Viewport and density: `1280 x 720` CSS pixels at device scale 1.
- State: dark theme, character edit drawer, derived state selected, real 511-episode project loaded.

## UX evidence

- The free-form episode text input is replaced by a compact summary trigger backed by `number[]` storage.
- The open picker combines current/all/clear shortcuts, direct episode jump, inclusive range addition, 50-episode segments, per-segment selection, and individual episode toggles.
- A 511-episode project renders 11 segment controls while only the active 50-episode slice is mounted in the grid.
- Shift-click range selection and Escape/outside-click dismissal are supported; the picker is teleported above drawer overflow and avoids the persistent footer.
- The closed trigger compresses selections into readable ranges such as `第 1 集、第 511 集 · 2 集` instead of rendering hundreds of chips.

## Interaction and regression checks

- Selected the `501–511` segment, added episode `511`, and confirmed the normalized summary in the real drawer.
- Component coverage includes range summaries, 240-episode segmentation, whole-segment selection, and drawer-footer persistence.
- Frontend suite: 76 files / 208 tests passed.
- Typecheck, production build, and `git diff --check` passed.

## Findings

- No actionable P0/P1/P2 findings remain.

## Final result

passed

---

# Asset Image Annotation Editor QA

- Source implementation: `/Users/anning/Projects/shengshimedia/frontend/src/features/viral-workbench/components/ReferenceImageAnnotationDialog.vue`
- Source visual truth: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-1b4b2ec0-6d14-4d5d-99cc-68a2ee080f4f.png`
- Implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/asset-image-annotation-editor.png`
- Route: `http://localhost:3000/#/create/short-drama/manual/9?chapter=1107`
- State: character asset drawer opened for `岳闻`, then annotation editor opened from the current image.

## Fidelity and interaction evidence

- The dark full-screen editor reproduces the source toolset: move, rectangle, ellipse, grid, arrow, freehand drawing, brush width, color, zoom, undo, and clear.
- The image remains centered in a bounded canvas and the footer communicates that saving creates a new image version instead of overwriting the source asset.
- Escape and the close button dismiss the editor; save remains unavailable until an annotation exists.
- Saving uploads the annotated PNG, atomically updates the current asset image, and creates a completed generation-history record.
- Browser verification covered editor launch and rendered controls; save/history persistence is covered by focused frontend and backend regression tests.
- Backend asset API tests: 17 passed.
- Frontend annotation geometry tests: 2 passed.
- Focused asset-dialog integration test: 1 passed.
- Typecheck, production build, and `git diff --check` passed.

## Findings

- No actionable P0/P1/P2 findings remain.

## Final result

passed

---

# Video Version Hover Boundary QA

- Source visual truth: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-2cffb59a-3b38-45f1-914d-1d29d66115fe.png`
- Implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/video-version-hover-boundary-fixed.png`
- Focused comparison: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/video-version-hover-boundary-comparison.png`
- Route: `http://localhost:3000/#/create/short-drama/storyboard/9?chapter=1107`
- Viewport and density: `1280 x 720` CSS pixels at device scale 1. The source is a `540 x 206` focused crop; the implementation evidence is a `520 x 83` focused component capture.
- State: light theme, successful current video plus failed generation version, failed version hovered.

## Focused interaction evidence

- Hover no longer applies vertical translation to either thumbnail; the measured computed transform is `none`.
- Hover preserves the thumbnail top coordinate at the version-button top coordinate (`328px`), so the top border remains fully inside the control.
- Both current and failed states retain their existing dimensions and labels; hover feedback is limited to border color and a compact shadow.
- Targeted component tests: 2 passed.
- Typecheck, production build, and `git diff --check` passed.

## Findings

- Resolved P2: `translateY(-1px)` moved the hovered thumbnail into the container boundary and visually covered the top border.
- No actionable P0/P1/P2 findings remain.

## Final result

passed

---

# Video Version Thumbnail Rail QA

- Source visual truth: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-add94f2e-ac2e-48a8-a3c5-2095812d1482.png`
- Implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/video-version-rail-implementation.png`
- Combined comparison: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/video-version-rail-comparison.png`
- Route: `http://localhost:3000/#/create/short-drama/storyboard/9?chapter=1107`
- Viewport and density: `1280 x 720` CSS pixels at device scale 1. Source image is `1264 x 232` pixels.
- State: light theme, one current successful video and one failed generation version.

## Full-view comparison evidence

- The previous `生成记录` header and large two-column record cards are removed.
- Version history now sits directly below the player as a compact centered thumbnail rail, matching the supplied reference structure.
- The rail remains visually subordinate to the player and does not increase the surrounding panel height.

## Focused region comparison evidence

- The current video is represented by a small thumbnail with a purple outline and `当前分镜` badge.
- The failed version remains a compact adjacent item; selecting it reveals detailed failure information only on demand.
- Successful non-current versions are selectable thumbnails and switch the active video through the existing parent event flow.

## Fidelity surfaces

- Typography: compact labels use the existing workbench type scale and do not introduce oversized card text.
- Spacing/layout: centered horizontal rail, tight thumbnail gaps, no visible scrollbar.
- Colors/tokens: current state uses the established purple accent; failed state uses the established red semantic token.
- Image quality: video poster thumbnails preserve aspect ratio with `object-fit: cover`.
- Copy/content: only state-oriented labels are shown; redundant model and parameter metadata are removed.

## Interaction and regression checks

- Clicking a successful non-current version emits the selection event and changes the active video.
- Clicking a failed version opens the focused error-detail dialog; the dialog closes normally and retains retry behavior.
- Targeted component tests: 2 passed.
- Typecheck and production build passed.
- Browser console after a clean reload contains only the pre-existing `app-theme-controller` injection warning; no current video-history component errors remain.

## Findings

- No actionable P0/P1/P2 findings remain.

## Comparison history

- Earlier implementation retained a `生成记录` title and large record cards, so it did not match the requested player-attached thumbnail rail.
- Fix: replaced the record-card layout with a centered compact version rail while retaining version switching and on-demand failure details.
- Post-fix evidence: the combined comparison image above.

## Final result

passed

---

# Chapter Video Editor QA

- Source visual truth: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-28ab6292-3cc1-4fd4-8cc5-88421ad8048e.png`
- Implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/chapter-video-editor-implementation.jpg`
- Side-by-side comparison: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/chapter-video-editor-comparison.jpg`
- Route: `#/create/short-drama/video/9?chapter=1107`
- Viewport: 1280 x 720
- Test state: chapter 1107 contains one playable completed scene video among twelve scenes.

## Entry and state evidence

- The video phase becomes available as soon as the current chapter has one completed video with a playable URL.
- A chapter without any playable completed video keeps the editor locked and shows the empty-state explanation.
- The timeline preserves completed, generating, failed, and pending scenes instead of hiding unavailable clips.

## Full-view comparison evidence

- The shared project header and episode rail remain fixed and mark the video phase as active.
- The player, transport controls, and full chapter timeline fit in the same desktop viewport.
- The selected scene, playback state, failed state, and pending state are visually distinct without adding a separate page shell.

## Interaction and regression checks

- Real media playback was verified with the existing completed video record.
- The edit action returns to the exact storyboard scene through `chapter=1107&scene=16`.
- Switching to chapter 1108 verified the no-video gate and switching back restored the playable editor.
- Browser console errors: none; only pre-existing theme injection warnings were present.
- Targeted frontend tests: 7 passed.
- Typecheck, production build, and `git diff --check` passed.

## Findings

- No actionable P0/P1/P2 findings remain.

## Final result

passed

---

# Storyboard Chapter Details and Prompt Formatting QA

- Source visual truth: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-499c2e7d-b2f3-476a-9722-d3acfb0af8ee.png`
- Storyboard implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/storyboard-chapter-prompt-qa.png`
- Chapter drawer implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/storyboard-chapter-drawer-qa.png`
- Route: `http://localhost:3000/#/create/short-drama/storyboard/9?chapter=1107`
- Viewport and density: `1280 x 720` CSS pixels at device scale 1.

## Full-view comparison evidence

- The existing three-column storyboard layout, episode rail, sticky chapter toolbar, model control, and shot actions remain aligned with the source view.
- The chapter summary is now a single compact interactive surface; opening it presents a right-side editing drawer without displacing the storyboard.
- The embedded prompt editor remains visually continuous with its model and generation controls while capping its editor viewport at 600px.

## Focused region comparison evidence

- Measured prompt editor height: `600px`.
- Measured prompt editor max height: `600px`.
- Prompt editor vertical overflow: `auto`; measured content scroll height: `646px`.
- The chapter drawer exposes labelled title and content fields, cancel/save actions, backdrop close, close icon, and Escape-key close.

## Fidelity surfaces

- Typography: chapter drawer and hover affordance reuse the workspace hierarchy and theme tokens.
- Spacing/layout: drawer width is bounded and responsive; the mobile chapter summary resets to full available width.
- Generated content: section titles render on their own lines; section bodies receive two full-width spaces of indentation; adjacent sections are separated by one blank line.
- Duration data: generated shot durations are represented as the existing `@{镜头时长:Ns}` editor controller token.

## Interaction and regression checks

- Clicked the live chapter summary and verified the edit drawer fields against current chapter data.
- Verified Escape closes the drawer without changing chapter data.
- Browser console errors: none. Existing unrelated theme-controller injection warnings remain.
- Backend prompt formatting tests: 20 passed.
- Targeted frontend component tests: 14 passed.
- Typecheck, production build, and `git diff --check` passed.

## Findings

- No actionable P0/P1/P2 findings remain.

## Final result

passed

---

# Storyboard Prompt Mention Editor QA

- Source visual truth: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-bea4940d-190b-46d6-b283-a5ff7785ab72.png`, `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-aa119f60-599b-4a69-a5da-96f5e460c332.png`, and `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-fd1ae6ce-2bff-4f48-83fb-48f3be8569fd.png`
- Implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/mention-editor-unified-duration-final.png`
- Route: `http://localhost:3000/#/create/short-drama/storyboard/9?chapter=1107`
- Viewport and density: `1280 x 720` CSS pixels at device scale 1.
- State: first storyboard scene visible with a selected scene asset and uploaded reference video; light and dark themes both verified.

## Full-view comparison evidence

- The prompt area retains the existing compact three-column storyboard layout and replaces only the plain textarea interaction layer.
- Users type `@` directly in the prompt; no redundant instruction strip or detached action toolbar is shown.
- The title, reference-media row, prompt content, model/parameter selectors, and generate action now share one clipped outer card. The editor no longer draws its own border, radius, shadow, or focus ring inside the parent surface.
- The bottom controls use the same transparent surface with no divider, so the complete generation editor reads as one continuous component.
- Persisted prompt syntax is rendered as inline chips while serialization remains plain text for autosave and model submission.

## Focused interaction evidence

- The mention picker opens next to the caret and lists only selected characters, selected scenes, and one `添加镜头时长` action; dialogue, station, continuation, props, uploaded images, and uploaded videos are intentionally excluded.
- Character and scene mentions use thumbnails where available. The duration action inserts a compact clock-icon token.
- Selecting `添加镜头时长` immediately opens and focuses the duration input; users no longer need to click the temporary token a second time.
- Clicking a duration token opens a 248px anchored popover with a decimal-capable `1–30` second input plus cancel/confirm controls.
- Confirmed durations serialize independently as JSON-safe prompt text such as `@{镜头时长:2.5s}` and render back as `2.5s` after reload.
- Clicking an image-backed mention opens the shared large preview with dimensions, format, zoom, reset, and Escape dismissal.
- Reference video mentions expose the first frame inline and open a native controlled video preview.

## Interaction and regression checks

- Verified the real 511-episode storyboard page with 13 rendered scene editors.
- Opened the mention picker and the large scene-image preview without mutating saved prompt content.
- Repeated the editor and mention-menu check in the Codex in-app browser under dark theme; surfaces, text, chips, borders, and active states follow the shared application tokens.
- Browser console errors: none.
- Latest targeted component tests: 3 files / 13 tests passed, including direct `@` insertion, immediate duration-popover focus, clock-icon rendering, duration limits, decimal serialization, persisted duration rendering, reference-media behavior, and model-aware video parameters.
- Typecheck, production build, and `git diff --check` passed.

## Findings

- No actionable P0/P1/P2 findings remain.

## Final result

passed

---

# Asset Variant Footer-Controlled Editing QA

- Source visual truth: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-850eb241-473b-4d2a-b725-7085520b1c11.png` and `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-dde1c082-79d7-492b-a033-1d0d326d03a0.png`
- Implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/asset-variant-footer-controlled-light-final.png`
- Side-by-side comparison: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/asset-variant-control-comparison.png`
- Route: `http://127.0.0.1:3000/#/create/short-drama/manual/9?chapter=1107`
- Viewport and density: `1280 x 720` CSS pixels at device scale 1. Source crops were normalized to the implementation region width in the comparison image.
- State: light theme, character edit drawer, `大师说的` derived state selected.

## Full-view comparison evidence

- The derived-state editor now contains fields only; upload, generate, cancel, and save actions are absent from the inline panel.
- Model options, cancel, regenerate, and version save remain in the persistent drawer footer and stay visible at the bottom of the viewport.
- The derived-state strip keeps the same compact thumbnail rhythm and selected outline as the source.

## Focused region comparison evidence

- The selected derived thumbnail exposes one compact `删除` tag inside its top-right corner; unselected tags remain hidden until hover/focus.
- The applicability field shows `AI 建议 · 可修改`, accepts mixed ranges such as `2-4、8`, and previews normalized episode chips.
- Browser inspection confirmed `0` buttons inside `.asset-variant-editor`; footer controls are `取消`, `重新生成`, and `保存此版本` plus generation options.

## Fidelity surfaces

- Typography: existing app type scale and optical weights are preserved; helper copy and episode chips use the established compact scale.
- Spacing/layout: inline action footer was removed, reducing vertical density; the three fields remain aligned in one row on desktop and collapse on mobile.
- Colors/tokens: all editor, AI badge, selected state, and delete-tag colors use existing light/dark theme tokens except the semantic red hover state.
- Image quality: existing source thumbnails and crops are unchanged.
- Copy/content: controls clearly state AI suggestion, human editability, and bottom-level persistence behavior.

## Interaction and regression checks

- Switched among base and derived states in the real drawer and verified the top image changes with selection.
- Confirmed existing and new variant drafts are persisted only when the drawer footer submits.
- Confirmed range parsing (`2-4、8` → `2,3,4,8`) and JSON editor-form persistence with component tests.
- Browser console errors: none.
- Frontend suite: 75 files / 205 tests passed.
- Typecheck, production build, and `git diff --check` passed.

## Findings

- No actionable P0/P1/P2 findings remain.

## Comparison history

- Earlier P2: delete tags were visible on every derived thumbnail, making the compact strip noisy.
- Fix: only the selected tag is persistent; other delete tags appear on hover or keyboard focus.
- Post-fix evidence: final light-theme implementation screenshot and combined comparison above.

## Final result

passed

---

# Asset Create Drawer Compact Header QA

- Source visual truth: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-aa4cac86-b7f0-403c-b103-cb0baac28649.png`
- Implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/asset-dialog-compact-header.png`
- Side-by-side comparison: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/asset-dialog-header-comparison.png`
- Route: `http://127.0.0.1:3000/#/create/short-drama/manual/9?chapter=1107`
- Viewport and density: `1280 x 720` CSS pixels at device scale 1.
- State: dark theme, project settings page, new character drawer open.

## Full-view comparison evidence

- The drawer retains the same form width and control alignment; only the title area was compacted.
- The first form row now begins immediately below the 64.4px header instead of after a large decorative band.

## Focused region comparison evidence

- Measured header height: `64.4px`.
- Header padding: `11px 18px`.
- Grid columns: `36px 1fr 32px`; the icon, title, and close control remain aligned and unobstructed.

## Fidelity surfaces

- Typography: title reduced to 17px and eyebrow to 8px while preserving hierarchy.
- Spacing/layout: icon tile reduced to 36px; gaps and outer padding tightened without changing form layout.
- Colors/tokens: existing light/dark theme tokens remain unchanged.
- Copy/content: unchanged.

## Interaction and regression checks

- Opened the real project settings page and the new-character drawer in the in-app browser.
- Browser console errors: none.
- Targeted component tests: 8 passed.
- Typecheck, production build, and `git diff --check` passed.

## Findings

- No actionable P0/P1/P2 findings remain.

## Final result

passed

---

# Asset Variant Delete Icon QA

- Source visual truth: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-588eec0b-3879-4f46-b065-3bfa3782c7ee.png`
- Implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/asset-variant-delete-icon-hover-visible.png`
- Route: `http://localhost:3000/#/create/short-drama/manual/9?chapter=1107`
- Viewport and density: `1280 x 720` CSS pixels at device scale 1. The source is a focused crop and the implementation capture shows the same hover state without density resampling.
- State: dark theme, character edit drawer, derived image hovered so its delete icon is visible.

## Full-view comparison evidence

- The variant strip retains its original compact horizontal layout and does not push the form controls out of position.
- Added rail spacing is confined to the variant strip and does not introduce a visible scrollbar.

## Focused region comparison evidence

- The delete button bounding box is fully inside the rail: `18.48 x 18.48` at `y=133.26`, while the rail begins at `y=128.5`.
- Hover opacity reaches `1`, and the complete circular button plus X icon is visible without clipping.

## Fidelity surfaces

- Typography: unchanged.
- Spacing/layout: the rail now reserves 10px above and 9px horizontally for floating controls; thumbnail dimensions and gaps remain unchanged.
- Colors/tokens: existing dark/light theme tokens and delete-button styling remain unchanged.
- Image quality: thumbnails retain their source crop and sizing.
- Copy/content: unchanged.

## Interaction and regression checks

- Created and hovered a temporary derived state, verified full delete-icon bounds, then deleted the temporary record.
- Browser console errors: none.
- Targeted component tests: 4 passed.
- Typecheck and production build passed.

## Findings

- No actionable P0/P1/P2 findings remain.

## Comparison history

- Earlier P2: negative icon offset placed part of the delete control outside the scroll container and clipped it.
- Fix: increased the rail's internal top and side padding while preserving thumbnail sizing and alignment.
- Post-fix evidence: the implementation screenshot and measured bounds above.

## Final result

passed

---

# Compact Video Generation History QA

- Source visual truth: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-ba79f3b7-2149-4a98-a3e8-d280a14a775f.png`
- Implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/video-history-page-implementation.png`
- Focused comparison: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/video-history-comparison.png`
- Route: `http://localhost:3000/#/create/short-drama/storyboard/9?chapter=1107`
- Viewport and density: `1280 x 720` CSS pixels at device scale 1.
- State: light theme, current successful video plus one failed generation record.

## Fidelity and interaction evidence

- History remains a compact two-column strip instead of expanding the preview panel.
- The active successful record is marked `当前`; completed non-current records remain selectable.
- Failed records expose only the compact `查看原因` action in the strip.
- The detailed, translated failure reason is absent from the document before activation and appears in a focused dialog only after clicking `查看原因`.
- Retry remains available from the failure dialog without turning the failed record into a selectable video version.
- Targeted component tests: 2 passed.
- Typecheck and production build passed.

## Findings

- No actionable P0/P1/P2 findings remain.

## Final result

passed

---

# Resolved Asset Variant Selection QA

- Source visual truth: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-d16f7067-a408-4ad1-a861-d95596a38e06.png`
- Implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/asset-variant-selection-resolved.png`
- Focused comparison: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/asset-variant-selection-comparison.png`
- Route: `http://localhost:3000/#/create/short-drama/storyboard/9?chapter=1107`
- Viewport and density: `1280 x 900` CSS pixels at device scale 1.
- State: light theme, character replacement picker opened from a row displaying `岳闻 · 古装形象`.

## Fidelity and interaction evidence

- The external row and the right-side picker selection now resolve the same chapter-applicable derived state.
- `岳闻 · 古装形象` is the checked current form; the base `岳闻` form is not selected.
- The left asset row still marks characters already present in the scene, while the right check marks the exact replacement target form.
- The active asset thumbnail uses the selected derivative image instead of the base image.
- Browser verification reported zero console errors.
- Targeted component tests: 6 passed.
- Typecheck, production build, and `git diff --check` passed.

## Findings

- No actionable P0/P1/P2 findings remain.

## Final result

passed

---

# Video Privacy Reference Nickname QA

- Source request: privacy failures must identify the known asset by nickname instead of forcing users to count provider reference-image positions.
- Implementation screenshot: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/nickname-video-error-card.png`
- Route: `http://localhost:3000/#/create/short-drama/storyboard/9?chapter=1107`
- State: dark theme, provider privacy rejection for an asset image whose resolved nickname is `陈经理`.

## Fidelity and interaction evidence

- The primary title now reads `参考图「陈经理」包含真人信息`; the provider position is no longer the user-facing identity.
- The error card shows the exact source thumbnail and nickname under `问题素材`.
- Provider position, raw error, request ID, and HTTP status remain available only in the expandable technical details.
- Clicking the problem-material row locates and briefly highlights the matching selected asset or uploaded image.
- The displayed nickname is derived from the same ordered request manifest used for outbound video reference images.
- Browser verification found the expected nickname title and zero console errors.
- Targeted component and shared-logic tests: 4 files / 9 tests passed.
- Typecheck, production build, and `git diff --check` passed.

## Findings

- No actionable P0/P1/P2 findings remain.

## Final result

passed
