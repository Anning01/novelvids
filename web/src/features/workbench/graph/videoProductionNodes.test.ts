import { describe, expect, it } from 'vitest'
import type { WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import { projectVideoResultEdge, videoResultOwners } from './videoProductionNodes'

function node(key: string, kind: WorkbenchNode['kind']): WorkbenchNode {
  return { id: 1, key, kind, backendKind: kind, title: key, position: { x: 0, y: 0 }, size: null, zIndex: 1, activeVersionId: null, status: 'ready', data: {}, createdAt: '', updatedAt: '' }
}

function edge(key: string, source: string, target: string, type: WorkbenchEdge['type'] = 'output_binding'): WorkbenchEdge {
  return { id: 1, key, source, target, type, backendType: type, sourceHandle: null, targetHandle: null, orderIndex: 0, config: null, createdAt: '', updatedAt: '' }
}

describe('video production node projection', () => {
  it('folds a bound video result into its production node', () => {
    const nodes = [node('video-production', 'shot'), node('video-result', 'video_result')]
    const owners = videoResultOwners(nodes, [edge('binding', 'video-production', 'video-result')])

    expect([...owners]).toEqual([['video-result', 'video-production']])
  })

  it('projects downstream result connections from the hidden result to the visible video node', () => {
    const owners = new Map([['video-result', 'video-production']])

    expect(projectVideoResultEdge(edge('downstream', 'video-result', 'composer'), owners)).toMatchObject({
      source: 'video-production',
      target: 'composer',
    })
  })
})
