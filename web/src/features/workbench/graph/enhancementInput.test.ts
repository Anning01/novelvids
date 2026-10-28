import { expect, it } from 'vitest'
import type { WorkbenchNode, WorkbenchEdge } from '../types/workbenchTypes'
import { enhancementInput } from './enhancementInput'
import { compatibleNodeCreations } from './nodeCreationRules'

function node(key: string, kind: WorkbenchNode['kind'], data: WorkbenchNode['data'] = {}): WorkbenchNode {
  return { id: 1, key, kind, backendKind: kind, title: key, position: { x: 0, y: 0 }, size: null, zIndex: 0, activeVersionId: null, status: 'ready', data, createdAt: '', updatedAt: '' }
}
const edge: WorkbenchEdge = { id: 1, key: 'edge', source: 'source', target: 'hd', type: 'output_binding', backendType: 'output_binding', sourceHandle: 'output-output', targetHandle: 'video-input', orderIndex: 0, config: null, createdAt: '', updatedAt: '' }

it('offers a directly connected HD video on both generated-video outputs', () => {
  for (const handleId of ['output-output','sequence-output']) {
    const options = compatibleNodeCreations({ nodeId: 'source', handleId, handleType: 'source' }, node('source','shot'), [
      { id: 'video_enhancement', label: '高清视频', description: '', kind: 'video_enhancement', data: {} },
    ])
    expect(options.map(item => [item.candidate.id,item.candidateHandleId,item.edgeType])).toEqual([['video_enhancement','video-input','output_binding']])
  }
})

it('follows the explicitly selected video instead of the newest version', () => {
  const source = node('source','shot',{ scene: { metadata: { workbench: { activeVideoId: 2 } } }, videos: [
    { id: 3, status: 3, url: '/new.mp4' }, { id: 2, status: 3, url: '/selected.mp4', metadata: { width: 1080, height: 1920 } },
  ] })
  expect(enhancementInput('hd',[source],[edge])).toMatchObject({ key: 'video:2', videoId: 2, shortSide: 1080 })
})

it('uses a completed enhancement as a new video source and rejects failed or unfinished results', () => {
  const source = node('source','video_enhancement',{ enhancement_result: { id: 50, status: 3, url: '/api/video/exports/50/download', output_probe: { width: 1920, height: 1080 } } })
  expect(enhancementInput('hd',[source],[edge])).toMatchObject({ key: 'export:50', exportId: 50, shortSide: 1080 })
  source.data.enhancement_result = { id: 50, status: 6, url: null }
  expect(enhancementInput('hd',[source],[edge])).toBeNull()
})
