# Storyboard Asset Layout QA

- Reference: `/var/folders/q5/q006z08s3sl7fmkzcwkrw9rc0000gn/T/codex-clipboard-7a68fcdb-fdad-4505-b254-1893a3dc4321.png`
- Implementation: `/Users/anning/.codex/visualizations/2026/08/13/019ff8d2-0137-7e41-a0b0-097ce4c18654/scene-assets-grid-picker.png`
- Viewport: `1280 × 720` CSS pixels.

## Verified

- Scene assets use a two-column visual grid with a full-width 16:9 image, replacement control, and action menu.
- Scene replacement picker opens 8px below the clicked scene control and retains base/derived-state selection.
- Character assets retain image, replacement control, voice control, and action menu.
- Prop assets use the character row layout without a voice column; their action menu aligns to the right.
- All three asset types share add, replace, edit, remove, and variant-selection behavior.
- No scene or prop voice controls are rendered.
- Light/dark tokens and overflow behavior remain intact.

## Final result

`passed`
