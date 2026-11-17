import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import SkillEditorDialog from './SkillEditorDialog.vue'
import { runSkillTrial, skillsApi, type CreativeSkill } from './skillsApi'
import { folderSkill, packageLimits, skillEntry } from '@/test/skillPackageFixture'

vi.mock('./skillsApi', () => ({ skillsApi: { models: vi.fn(), detail: vi.fn(), packageFormat: vi.fn(), update: vi.fn(), create: vi.fn() }, runSkillTrial: vi.fn() }))
vi.mock('./SkillMarkdownEditor.vue', () => ({ default: { props: ['modelValue', 'disabled'], emits: ['update:modelValue'], template: '<textarea name="skill-instructions" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' } }))
const source: CreativeSkill = { id: 3, version: 4, name: '我的方法', task: 'story', description: '', instructions: '# 原文\n{{input}}', references: [], is_active: true, builtin: false }
let wrapper: ReturnType<typeof mount>
const modal = () => new DOMWrapper(document.body).get('dialog[open]')
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(skillsApi.models).mockResolvedValue({ code: 0, message: '', data: [{ id: 9, name: '测试模型', model: 'model' }] })
  vi.mocked(skillsApi.detail).mockImplementation(async (_id, task) => ({ code: 0, message: '', data: folderSkill({ ...source, task }) }))
  vi.mocked(skillsApi.packageFormat).mockResolvedValue({ code: 0, message: '', data: { files: [{ path: 'SKILL.md', content: skillEntry(''), encoding: 'utf-8' }], limits: packageLimits } })
})
afterEach(() => wrapper?.unmount())

it('tests unsaved Markdown without saving and selects model preferences within the modal', async () => {
  wrapper = mount(SkillEditorDialog, { props: { task: 'story', source } })
  await flushPromises()
  await modal().get('textarea[name="skill-instructions"]').setValue(skillEntry('# 未保存\n{{input}}'))
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
  expect(runSkillTrial).toHaveBeenCalledWith(expect.objectContaining({ skill: expect.objectContaining({ files: [expect.objectContaining({ content: skillEntry('# 未保存\n{{input}}') })] }), input: '测试素材', model_config_id: 9, thinking: 'enabled', reasoning_effort: null }), expect.any(AbortSignal), expect.any(Function))
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

it('focuses the safe confirmation action when closing a dirty editor and never discards on repeated Escape', async () => {
  wrapper = mount(SkillEditorDialog, { props: { task: 'story', source } })
  await flushPromises()
  await modal().get('textarea[name="skill-instructions"]').setValue(skillEntry('# changed'))
  await modal().get('button[aria-label="关闭"]').trigger('click')
  const resume = modal().findAll('button').find(item => item.text() === '继续编辑')!
  expect(document.activeElement).toBe(resume.element)
  expect(resume.attributes('aria-describedby')).toBeTruthy()
  await modal().trigger('cancel')
  expect(modal().attributes('open')).toBeDefined()
  await resume.trigger('click')
  expect(document.activeElement).toBe(modal().get('textarea[name="skill-instructions"]').element)
  expect(modal().get('.discard-area').attributes('aria-hidden')).toBe('true')
})

it('sends trial settings separately while saving a skill without placeholders unchanged', async () => {
  const instructions = '按剧情自然展开，保留关键对白。'
  wrapper = mount(SkillEditorDialog, { props: { task: 'screenplay', source: { ...source, task: 'screenplay', instructions } } })
  await flushPromises()
  expect(modal().get('.trial-parameters summary').text()).toBe('试运行设置')
  expect(modal().get('.trial-parameters').text()).not.toContain('占位符')
  expect(modal().find('.trial-parameters code').exists()).toBe(false)
  await modal().get('textarea[name="skill-instructions"]').setValue(skillEntry(instructions))
  await modal().get('button[aria-label="本集节奏"]').trigger('click')
  const menu = new DOMWrapper(document.body).get('[role="listbox"][aria-label="本集节奏"]')
  await menu.findAll('[role="option"]').find(option => option.text() === '快节奏')!.trigger('click')
  const seconds = modal().get('input[name="trial-max-seconds"]')
  expect(seconds.attributes('form')).toBe('')
  expect(seconds.attributes('min')).toBe('1')
  await seconds.setValue('75')
  await modal().get('.trial-input').setValue('渡口来了一条陌生的船。')
  vi.mocked(runSkillTrial).mockResolvedValueOnce()
  await modal().findAll('button').find(button => button.text() === '发送')!.trigger('click')
  await flushPromises()
  expect(runSkillTrial).toHaveBeenCalledWith(expect.objectContaining({
    skill: expect.objectContaining({ files: [expect.objectContaining({ content: skillEntry(instructions) })] }), episode_pacing: { preset: 'fast', max_seconds: 75 },
  }), expect.any(AbortSignal), expect.any(Function))
  expect(skillsApi.update).not.toHaveBeenCalled()
  vi.mocked(skillsApi.update).mockImplementation(async (id, body) => ({ code: 0, message: '', data: { ...body, id, version: 5, builtin: false } }))
  await modal().get('form').trigger('submit')
  await flushPromises()
  expect(skillsApi.update).toHaveBeenCalledWith(3, expect.objectContaining({ files: [expect.objectContaining({ content: skillEntry(instructions) })] }), 4)
  expect(vi.mocked(skillsApi.update).mock.calls[0]![1]).not.toHaveProperty('episode_pacing')
})

it('preserves legacy placeholder text without turning it into skill settings', async () => {
  const instructions = '节奏 {{episode_pacing}}；参考 {{max_seconds}} 秒'
  vi.mocked(skillsApi.detail).mockResolvedValueOnce({ code: 0, message: '', data: folderSkill({ ...source, task: 'screenplay', instructions }) })
  wrapper = mount(SkillEditorDialog, { props: { task: 'screenplay', source: { ...source, task: 'screenplay', instructions } } })
  await flushPromises()
  expect(modal().get('textarea[name="skill-instructions"]').element).toHaveProperty('value', skillEntry(instructions))
  expect(modal().find('.trial-parameters code').exists()).toBe(false)
  await modal().get('.trial-input').setValue('测试素材')
  vi.mocked(runSkillTrial).mockResolvedValueOnce()
  await modal().findAll('button').find(button => button.text() === '发送')!.trigger('click')
  await flushPromises()
  expect(runSkillTrial).toHaveBeenCalledWith(expect.objectContaining({
    skill: expect.objectContaining({ files: [expect.objectContaining({ content: skillEntry(instructions) })] }),
    episode_pacing: { preset: 'smart', max_seconds: null },
  }), expect.any(AbortSignal), expect.any(Function))
})

it.each(['0', '1.5'])('reveals invalid trial duration %s before sending', async seconds => {
  wrapper = mount(SkillEditorDialog, { props: { task: 'screenplay', source } })
  await flushPromises()
  await modal().get('input[name="trial-max-seconds"]').setValue(seconds)
  await modal().get('.trial-input').setValue('测试素材')
  await modal().findAll('button').find(button => button.text() === '发送')!.trigger('click')
  expect(runSkillTrial).not.toHaveBeenCalled()
  expect(modal().get<HTMLDetailsElement>('.trial-parameters').element.open).toBe(true)
})
