import { expect, it } from 'vitest'
import type { WorkbenchNodeCreationCandidate } from './nodeCreationRules'
import { compatibleNodeCreations } from './nodeCreationRules'

const candidates: WorkbenchNodeCreationCandidate[] = [
  { id: 'asset', label: '空白资产', description: '', kind: 'asset', data: {} },
  { id: 'shot', label: '镜头', description: '', kind: 'shot', data: {} },
  { id: 'watermark', label: '创建水印', description: '', kind: 'watermark', data: {} },
  { id: 'operation:video_composer', label: '视频合成器', description: '', kind: 'video_composer', data: {} },
]

it('offers only nodes compatible with an asset output', () => {
  const options = compatibleNodeCreations(
    { nodeId: 'asset-1', handleId: 'asset-output', handleType: 'source' },
    { kind: 'asset', data: {} },
    candidates,
  )

  expect(options.map(option => [option.candidate.id, option.candidateHandleId, option.edgeType])).toEqual([
    ['asset', 'asset-input', 'asset_reference'],
    ['shot', 'asset-input', 'asset_reference'],
  ])
})

it('offers a video composer for a shot sequence output', () => {
  const options = compatibleNodeCreations(
    { nodeId: 'shot-1', handleId: 'sequence-output', handleType: 'source' },
    { kind: 'shot', data: {} },
    candidates,
  )

  expect(options.map(option => [option.candidate.id, option.candidateHandleId, option.edgeType])).toEqual([
    ['shot', 'sequence-input', 'shot_sequence'],
    ['operation:video_composer', 'shot-input', 'output_binding'],
  ])
})

it('supports reverse creation from a required watermark video input', () => {
  const options = compatibleNodeCreations(
    { nodeId: 'watermark-1', handleId: 'watermark-video-input', handleType: 'target' },
    { kind: 'watermark', data: {} },
    candidates,
  )

  expect(options.map(option => [option.candidate.id, option.candidateHandleId, option.edgeType])).toEqual([
    ['shot', 'output-output', 'output_binding'],
    ['watermark', 'output-output', 'output_binding'],
    ['operation:video_composer', 'output-output', 'output_binding'],
  ])
})
