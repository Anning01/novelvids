import { expect, it } from 'vitest'
import type { WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import {
  COMPOSER_ASPECT_RATIOS,
  COMPOSER_RESOLUTIONS,
  moveOrder,
  normalizeComposerConfig,
  orderedComposerInputs,
} from './composerConfig'

const timestamp = '2026-07-25T00:00:00.000Z'
const nodes = [{
  id: 1,
  key: 'video-1',
  kind: 'video_result',
  data: { video: { id: 1, url: '/one.mp4', metadata: { duration: 4 } } },
}, {
  id: 2,
  key: 'video-2',
  kind: 'video_media',
  data: { url: '/two.mp4', durationSeconds: 6 },
}].map(item => ({
  backendKind: item.kind,
  title: item.key,
  position: { x: 0, y: 0 },
  size: null,
  zIndex: 1,
  activeVersionId: null,
  status: 'ready',
  createdAt: timestamp,
  updatedAt: timestamp,
  ...item,
})) as WorkbenchNode[]

function composerEdge(source: string, orderIndex: number): WorkbenchEdge {
  return {
    id: orderIndex + 1,
    key: `${source}-composer-1`,
    source,
    target: 'composer-1',
    type: 'output_binding',
    backendType: 'output_binding',
    sourceHandle: 'output',
    targetHandle: 'video-input',
    orderIndex,
    config: null,
    createdAt: timestamp,
    updatedAt: timestamp,
  }
}

it('orders connected videos by explicit edge orderIndex and reads media details', () => {
  const result = orderedComposerInputs('composer-1', nodes, [
    composerEdge('video-2', 1),
    composerEdge('video-1', 0),
  ])
  expect(result).toEqual([
    { key: 'video-1', title: 'video-1', url: '/one.mp4', durationSeconds: 4, orderIndex: 0, sourceKind: 'video_result' },
    { key: 'video-2', title: 'video-2', url: '/two.mp4', durationSeconds: 6, orderIndex: 1, sourceKind: 'video_media' },
  ])
})

it('moves one clip without disturbing the remaining order', () => {
  expect(moveOrder(['a', 'b', 'c'], 'b', 'up')).toEqual(['b', 'a', 'c'])
  expect(moveOrder(['a', 'b', 'c'], 'b', 'down')).toEqual(['a', 'c', 'b'])
  expect(moveOrder(['a', 'b', 'c'], 'a', 'up')).toEqual(['a', 'b', 'c'])
  expect(moveOrder(['a', 'b', 'c'], 'c', 'down')).toEqual(['a', 'b', 'c'])
})

it('matches the reference resolution and aspect-ratio options', () => {
  expect(COMPOSER_RESOLUTIONS).toEqual(['480p', '720p', '1080p', '4k'])
  expect(COMPOSER_ASPECT_RATIOS).toEqual(['16:9', '4:3', '1:1', '3:4', '9:16', '21:9'])
  expect(normalizeComposerConfig({ name: '', resolution: 'invalid', aspectRatio: 'bad' } as never)).toEqual({
    name: '视频合成器',
    resolution: '720p',
    aspectRatio: '9:16',
  })
})
