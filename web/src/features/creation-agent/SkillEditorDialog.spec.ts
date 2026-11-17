import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import SkillEditorDialog from './SkillEditorDialog.vue'
import { runSkillTrial, skillsApi, type CreativeSkill } from './skillsApi'

vi.mock('./skillsApi', () => ({ skillsApi: { models: vi.fn(), update: vi.fn(), create: vi.fn() }, runSkillTrial: vi.fn() }))
vi.mock('./SkillMarkdownEditor.vue', () => ({ default: { props: ['modelValue', 'disabled'], emits: ['update:modelValue'], template: '<textarea name="skill-instructions" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' } }))
const source: CreativeSkill = { id: 3, version: 4, name: '我的方法', task: 'story', description: '', instructions: '# 原文\n{{input}}', references: [], is_active: true, builtin: false }
let wrapper: ReturnType<typeof mount>
const modal = () => new DOMWrapper(document.body).get('dialog[open]')
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(skillsApi.models).mockResolvedValue({ code: 0, message: '', data: [{ id: 9, name: '测试模型', model: 'model' }] })
})
afterEach(() => wrapper?.unmount())

it('tests unsaved Markdown without saving and selects model preferences within the modal', async () => {
  wrapper = mount(SkillEditorDialog, { props: { task: 'story', source } })
  await flushPromises()
  await modal().get('textarea[name="skill-instructions"]').setValue('# 未保存\n{{input}}')
  await modal().get('.trial-input').setValue('测试素材')
  await modal().get('button[aria-label="思考模式"]').trigger('click')
  const menu = new DOMWrapper(document.body).get('[role="listbox"][aria-label="思考模式"]')
  expect(menu.element.closest('dialog')).toBe(modal().element)
  await menu.findAll('[role="option"]')[1]!.trigger('click')
  vi.mocked(runSkillTrial).mockImplementation(async (_body, _signal, emit) => {
    emit({ type: 'status', status: 'running' }); emit({ type: 'thinking', delta: '公开摘要' })
    emit({ type: 'output', delta: '{"story_outline":"结果"}' }); emit({ type: 'done', usage: { input_tokens: 10, output_tokens: 6 } })
  })
  await modal().findAll('button').find(item => item.text() === '发送')!.trigger('click')
  await flushPromises()
  expect(runSkillTrial).toHaveBeenCalledWith(expect.objectContaining({ skill: expect.objectContaining({ instructions: '# 未保存\n{{input}}' }), input: '测试素材', model_config_id: 9, thinking: 'enabled', reasoning_effort: null }), expect.any(AbortSignal), expect.any(Function))
  expect(skillsApi.update).not.toHaveBeenCalled()
  expect(modal().get('.model-output').text()).toContain('结果')
  expect(modal().get('.model-thoughts').text()).toContain('公开摘要')
  expect(modal().text()).toContain('16 tokens')
})

it('stops an in-flight request while keeping the draft and output', async () => {
  vi.mocked(runSkillTrial).mockImplementation((_body, signal, emit) => new Promise((_resolve, reject) => {
    emit({ type: 'output', delta: '部分结果' })
    signal.addEventListener('abort', () => reject(new DOMException('Stopped', 'AbortError')))
  }))
  wrapper = mount(SkillEditorDialog, { props: { task: 'story', source } })
  await flushPromises()
  await modal().get('.trial-input').setValue('素材')
  await modal().findAll('button').find(item => item.text() === '发送')!.trigger('click')
  expect(modal().get('button[type="submit"]').attributes('disabled')).toBeDefined()
  await modal().findAll('button').find(item => item.text() === '停止')!.trigger('click')
  await flushPromises()
  expect(modal().get('.model-output').text()).toBe('部分结果')
  expect(modal().text()).toContain('已停止')
  expect(skillsApi.update).not.toHaveBeenCalled()
})
