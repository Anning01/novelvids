import { expect, it } from 'vitest'
import { workbenchNodeHandles } from './handleCapabilities'

it('exposes separate asset-reference and video-composition outputs for uploaded video media', () => {
  expect(workbenchNodeHandles('video_media').source.map(handle => handle.id)).toEqual([
    'asset-output',
    'output-output',
  ])
  expect(workbenchNodeHandles('video_media').target).toEqual([])
})
