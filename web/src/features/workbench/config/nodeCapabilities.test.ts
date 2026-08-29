import { expect, it } from 'vitest'
import type { WorkbenchNodeKind } from '../types/workbenchTypes'
import { workbenchNodeHandles } from '../graph/handleCapabilities'
import { NODE_CAPABILITIES } from './nodeCapabilities'

it('defines one exhaustive capability entry for every workbench node kind', () => {
  const kinds = [
    'chapter',
    'source_video',
    'ai_decomposition',
    'asset',
    'audio_reference',
    'digital_human',
    'image_media',
    'video_media',
    'audio_media',
    'shot',
    'video_result',
    'watermark',
    'video_composer',
    'section',
    'note',
    'unsupported',
  ] satisfies WorkbenchNodeKind[]

  expect(Object.keys(NODE_CAPABILITIES)).toEqual(kinds)
})

it('keeps editing and port behavior consistent for manual operation nodes', () => {
  expect(NODE_CAPABILITIES.chapter).toMatchObject({ deletable: false, target: false, source: false })
  expect(workbenchNodeHandles('chapter')).toEqual({ target: [], source: [] })
  expect(NODE_CAPABILITIES.source_video).toMatchObject({ deletable: false, runnable: false })
  expect(NODE_CAPABILITIES.ai_decomposition).toMatchObject({ deletable: false, runnable: false })
  expect(NODE_CAPABILITIES.note).toMatchObject({ deletable: true, copyable: true, target: false, source: false })
  expect(NODE_CAPABILITIES.section).toMatchObject({ deletable: true, copyable: false, target: false, source: false })
  expect(NODE_CAPABILITIES.watermark).toMatchObject({ deletable: true, runnable: true, target: true, source: true })
  expect(NODE_CAPABILITIES.video_composer).toMatchObject({ deletable: true, runnable: true, target: true, source: true })
})
