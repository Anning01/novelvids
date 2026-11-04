import { describe, expect, it } from 'vitest'
import { injectLastFrameContinuityInstruction, rebaseLastFrameContinuity } from './lastFrameContinuity'

describe('injectLastFrameContinuityInstruction', () => {
  const first = '【首帧衔接】\n@{参考图片:%2Fmedia%2Flast-1.png} 作为本镜头首帧。'
  const replacement = '【首帧衔接】\n@{参考图片:%2Fmedia%2Flast-2.png} 作为本镜头首帧。'

  it('在当前草稿前注入首帧用途并保持幂等', () => {
    const injected = injectLastFrameContinuityInstruction('【镜头描述】\n人物起身', first)
    expect(injected).toBe(`${first}\n\n【镜头描述】\n人物起身`)
    expect(injectLastFrameContinuityInstruction(injected, first)).toBe(injected)
  })

  it('替换旧尾帧指令且保留用户当前草稿', () => {
    const current = `${first}\n\n【镜头描述】\n用户刚修改的动作`
    expect(injectLastFrameContinuityInstruction(current, replacement)).toBe(
      `${replacement}\n\n【镜头描述】\n用户刚修改的动作`,
    )
  })
})

it('replaces an English continuity instruction without duplicating the section', () => {
  const first = '[First-frame continuity]\nImage 1 is the opening frame.\n\nAlex: Stay here.'
  const instruction = '[First-frame continuity]\nImage 2 is the opening frame.'
  const result = injectLastFrameContinuityInstruction(first, instruction)
  expect(result).toBe(instruction + '\n\nAlex: Stay here.')
})

it.each(['【首帧衔接】\n首帧参考：@{参考图片:new}', '[First-frame continuity]\nFirst-frame reference: @{参考图片:new}'])(
  'reconciles the saved prefix while keeping unsaved local changes (%s)', instruction => {
    const base = 'Original action'
    const saved = `${instruction}\n\nOriginal action`
    expect(rebaseLastFrameContinuity(base, 'Local edited action', saved, instruction)).toEqual({
      basePrompt: saved, prompt: `${instruction}\n\nLocal edited action`,
    })
    expect(rebaseLastFrameContinuity(base, 'Local edited action', `${instruction}\n\nSomeone else changed the action`, instruction)).toBeNull()
    expect(rebaseLastFrameContinuity(base, 'Local edited action', base, 'unrecognized instruction')).toBeNull()
  },
)

it('reconciles a legacy protocol prefix without retaining the old JSON in either version', () => {
  const base = '{"first_frame_reference": "@{参考图片:old}"}\n\nOriginal action'
  const instruction = '【首帧衔接】\n首帧参考：@{参考图片:new}'
  expect(rebaseLastFrameContinuity(base, base.replace('Original action', 'Local action'), `${instruction}\n\nOriginal action`, instruction)).toEqual({
    basePrompt: `${instruction}\n\nOriginal action`, prompt: `${instruction}\n\nLocal action`,
  })
})
