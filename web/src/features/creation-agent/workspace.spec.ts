import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { useCreationAgentWorkspace } from './workspace'

const identity = vi.hoisted(() => ({ token: 'one', team: 1 }))
vi.mock('@/api', () => ({ getAuthToken: () => identity.token, getActiveTeamId: () => identity.team }))
beforeEach(() => { setActivePinia(createPinia()); identity.token = 'one'; identity.team = 1 })

it('keeps the assistant, chosen model, and conversation drafts when navigating production steps', () => {
  const workspace = useCreationAgentWorkspace()
  workspace.editTargets(7, 3, [{ target: { kind: 'variant', id: 701 }, label: '女主 · 雨夜风衣' }])
  workspace.modelId = '8'
  workspace.drafts['conversation:9'] = '光线更柔和，保留衣服颜色'
  workspace.enterProject(7)
  workspace.enterChapter(3)
  expect(workspace.isOpen).toBe(true)
  expect(workspace.selection[0]?.target).toEqual({ kind: 'variant', id: 701 })
  expect(workspace.modelId).toBe('8')
  expect(workspace.drafts['conversation:9']).toContain('保留衣服颜色')
  workspace.enterChapter(4)
  expect(workspace.selection).toEqual([])
  expect(workspace.isOpen).toBe(true)
  expect(workspace.drafts['conversation:9']).toContain('保留衣服颜色')
})

it.each(['project', 'account', 'team'])('clears private drafts, model and scope on %s changes', change => {
  const workspace = useCreationAgentWorkspace()
  workspace.editTargets(7, 3, [{ target: { kind: 'scene', id: 9 }, label: '分镜 1' }])
  workspace.drafts.new = 'private draft'
  workspace.modelId = '8'
  if (change === 'account') identity.token = 'two'
  if (change === 'team') identity.team = 2
  workspace.enterProject(change === 'project' ? 8 : 7)
  expect(workspace.drafts).toEqual({})
  expect(workspace.selection).toEqual([])
  expect(workspace.modelId).toBe('')
  expect(workspace.isOpen).toBe(false)
})
