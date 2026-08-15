import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/features/workbench/styles/workbench.css', 'utf8')

describe('borderless media node spacing', () => {
  it('keeps the flush body override more specific than the shared body rule', () => {
    expect(css).toMatch(/\.workbench-node-frame__body\.workbench-node-frame__body--flush\s*\{[^}]*padding:\s*0;/s)
  })

  it('does not reserve form spacing below borderless asset media', () => {
    expect(css).toMatch(/:last-child:not\(\.workbench-asset-image-stage, \.workbench-asset-gallery, \.workbench-asset-default-image\)\s*\{[^}]*margin-bottom:\s*14px;/s)
  })

  it('lets shot video media touch the borderless node on every side', () => {
    expect(css).toMatch(/\.vue-flow__node-shot[^}]*\.workbench-node-frame\.is-borderless-media\s*\{[^}]*border:\s*0;/s)
    expect(css).toMatch(/\.vue-flow__node-shot[^}]*\.workbench-video-production\s*>\s*\.workbench-video-result\s*\{[^}]*margin:\s*0;/s)
  })
})
