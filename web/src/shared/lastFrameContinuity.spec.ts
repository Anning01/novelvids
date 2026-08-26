import { describe, expect, it } from 'vitest'
import { injectLastFrameContinuityInstruction } from './lastFrameContinuity'

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
