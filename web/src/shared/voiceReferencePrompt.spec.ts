import { describe, expect, it } from 'vitest'
import {
  buildVoiceReferenceMappings,
  injectEditableVoiceReferenceInstruction,
  renderVoiceReferenceInstruction,
} from './voiceReferencePrompt'

describe('可编辑音色参考 Prompt', () => {
  const assets = [
    { assetId: 10, name: '总工程师', aliases: ['工程师'], referenceId: 21 },
    { assetId: 11, name: '林冲', aliases: [], referenceId: 22 },
  ]

  it('按旁白和角色在镜头中的引用顺序生成音频映射', () => {
    const mappings = buildVoiceReferenceMappings({
      prompt: '@林冲看向@总工程师。',
      promptParams: { narration: ['0.0s-1.0s: 旁白：清晨降临。'] },
      narratorReferenceId: 20,
      assets,
    })

    expect(mappings).toEqual([
      { referenceId: 20, kind: 'narrator', subjects: ['旁白'] },
      { referenceId: 22, kind: 'character', subjects: ['林冲'] },
      { referenceId: 21, kind: 'character', subjects: ['总工程师'] },
    ])
    expect(renderVoiceReferenceInstruction(mappings)).toContain('角色音色参考：')
    expect(renderVoiceReferenceInstruction(mappings)).toContain('@音频1 对应旁白')
    expect(renderVoiceReferenceInstruction(mappings)).toContain('@音频2 对应角色 @{林冲}')
    expect(renderVoiceReferenceInstruction(mappings)).toContain('该音频仅用于参考对应角色的音色')
    expect(renderVoiceReferenceInstruction(mappings)).toContain('不得复述样本原话')
  })

  it('角色缺少 @ 标注但存在台词时仍生成音色说明', () => {
    const mappings = buildVoiceReferenceMappings({
      prompt: '总工程师（低声）：开始执行。',
      assets,
    })

    expect(mappings).toEqual([
      { referenceId: 21, kind: 'character', subjects: ['总工程师'] },
    ])
  })

  it('注入到角色参考之后，不放在提示词末尾', () => {
    const mappings = [{
      referenceId: 21,
      kind: 'character' as const,
      subjects: ['总工程师'],
    }]
    const injected = injectEditableVoiceReferenceInstruction(
      '【角色 / 道具 / 场景引用】\n角色参考：@总工程师\n角色设定图：@总工程师\n\n【镜头描述】\n人物开口',
      mappings,
    )
    expect(injected).toContain('角色参考：@总工程师\n角色音色参考：\n@音频1 对应角色 @{总工程师}')
    expect(injected.indexOf('角色音色参考：')).toBeLessThan(injected.indexOf('【镜头描述】'))

    const adjusted = injected.replace('音域、语速和说话质感', '声音更低沉，语速更慢')
    expect(injectEditableVoiceReferenceInstruction(adjusted, mappings)).toBe(adjusted)
  })

  it('将旧版末尾音色段迁移到角色引用区', () => {
    const prompt = '【角色 / 道具 / 场景引用】\n角色参考：@林冲\n\n【镜头描述】\n林冲开口\n\n【音色参考】\n[音频1] 旧说明'
    const migrated = injectEditableVoiceReferenceInstruction(prompt, [{
      referenceId: 22,
      kind: 'character',
      subjects: ['林冲'],
    }])

    expect(migrated).not.toContain('【音色参考】')
    expect(migrated).toContain('角色参考：@林冲\n角色音色参考：\n@音频1 对应角色 @{林冲}')
  })

  it('将已有的方括号音频引用升级为 @ 引用并补齐角色映射', () => {
    const prompt = '【角色 / 道具 / 场景引用】\n角色参考：@{林冲}\n角色音色参考：\n[音频1] 仅用于参考角色“林冲”的音色。'
    const migrated = injectEditableVoiceReferenceInstruction(prompt, [{
      referenceId: 22,
      kind: 'character',
      subjects: ['林冲'],
    }])

    expect(migrated).toContain('@音频1 对应角色 @{林冲}；该音频仅用于参考对应角色的音色。')
    expect(migrated).not.toContain('[音频1]')
  })
})
