import { afterEach, describe, expect, it } from 'vitest'
import { creationAgentToolOperationLabel, creationAgentToolProgressLabel } from './toolPresentation'
import { setLocale } from '@/i18n'
afterEach(() => setLocale('zh'))
describe('shared Agent tool presentation', () => {
  it('reuses the existing progress wording and hides internal names for local terminal tools', () => {
    expect(creationAgentToolOperationLabel('read_creation_history')).toBe('回查对话历史')
    expect(creationAgentToolProgressLabel('read_creation_history')).toBe('正在回查对话历史')
    expect(creationAgentToolProgressLabel('get_creation_context')).toBe('正在读取创作上下文')
    expect(creationAgentToolOperationLabel('finish_creation_reply')).toBe('保存回复与长期规则')
    expect(creationAgentToolOperationLabel('read_creation_prompt_page')).toBe('读取提示词原文')
    expect(creationAgentToolProgressLabel('read_creation_prompt_page')).toBe('正在读取提示词原文')
    expect(creationAgentToolOperationLabel('list_creation_objects')).toBe('浏览作品对象')
    expect(creationAgentToolProgressLabel('read_creation_references')).toBe('正在查看对象引用')
    expect(creationAgentToolOperationLabel('unknown_tool_id')).toBe('处理本地任务')
  })
  it('localizes both presentations at call time', () => {
    setLocale('en')
    expect(creationAgentToolOperationLabel('read_creation_history')).toBe('Review conversation history')
    expect(creationAgentToolProgressLabel('read_creation_history')).toBe('Reviewing conversation history')
    expect(creationAgentToolOperationLabel('finish_creation_reply')).toBe('Save reply and continuing rules')
    expect(creationAgentToolProgressLabel('get_creation_context')).toBe('Reading creative context')
    expect(creationAgentToolOperationLabel('read_creation_prompt_page')).toBe('Read prompt text')
    expect(creationAgentToolProgressLabel('read_creation_prompt_page')).toBe('Reading prompt text')
    expect(creationAgentToolOperationLabel('list_creation_objects')).toBe('Browse project objects')
    expect(creationAgentToolProgressLabel('read_creation_references')).toBe('Reading object references')
  })
})
