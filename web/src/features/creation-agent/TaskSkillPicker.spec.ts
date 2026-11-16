import { DOMWrapper, mount, flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import TaskSkillPicker from './TaskSkillPicker.vue'
import { skillsApi, type CreativeSkill } from './skillsApi'

vi.mock('./skillsApi', () => ({ skillsApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), setDefault: vi.fn() } }))
const modal = () => new DOMWrapper(document.body).get<HTMLDialogElement>('dialog[open]')

const builtin: CreativeSkill = { id: 0, task: 'story', name: '故事分析', description: '', instructions: '内置分析方法', references: [], builtin: true, is_active: true }
const custom: CreativeSkill = { ...builtin, id: 5, name: '我的悬疑', builtin: false, version: 2 }
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(skillsApi.list).mockResolvedValue({ code: 0, message: '', data: { items: [builtin, custom], default_skill_id: 0 } })
  vi.mocked(skillsApi.create).mockImplementation(async body => ({ code: 0, message: '', data: { ...body, id: 6, version: 1, builtin: false } }))
  vi.mocked(skillsApi.update).mockImplementation(async (id, body) => ({ code: 0, message: '', data: { ...body, id, version: 3, builtin: false } }))
  vi.mocked(skillsApi.setDefault).mockResolvedValue({ code: 0, message: '', data: null })
})

it.each(['light', 'dark'])('uses the shared selector and supports keyboard selection in %s mode', async theme => {
  const host = document.createElement('div')
  host.dataset.appTheme = theme
  document.body.append(host)
  const wrapper = mount(TaskSkillPicker, { attachTo: host, props: { task: 'story' } })
  try {
    const trigger = wrapper.get('button[aria-label="故事分析技能"]')
    expect(trigger.attributes('disabled')).toBeDefined()
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toEqual([[0]])
    expect(wrapper.find('select').exists()).toBe(false)
    expect(wrapper.get('.app-select').classes()).toContain('is-compact')
    await trigger.trigger('keydown', { key: 'ArrowDown' })
    const menu = document.querySelector('[role="listbox"][aria-label="故事分析技能"]')!
    const [first, second] = [...menu.querySelectorAll<HTMLButtonElement>('[role="option"]')]
    expect(document.activeElement).toBe(first)
    first!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    expect(document.activeElement).toBe(second)
    second!.click()
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([5])
    expect(document.activeElement).toBe(trigger.element)
    expect(trigger.attributes('aria-expanded')).toBe('false')
  } finally { wrapper.unmount(); host.remove() }
})

it('copies a built-in method without submitting an output protocol', async () => {
  const wrapper = mount(TaskSkillPicker, { props: { task: 'story', modelValue: 0 } })
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '复制并编辑')!.trigger('click')
  expect(wrapper.find('form').exists()).toBe(false)
  expect(modal().element.parentElement).toBe(document.body)
  expect(modal().element.open).toBe(true)
  expect(modal().get('h2').text()).toBe('创建我的技能')
  expect(modal().get('input[name="skill-name"]').attributes('autofocus')).toBeDefined()
  expect(modal().get('textarea[name="skill-instructions"]').element).toHaveValue('内置分析方法')
  await modal().get('input[name="skill-name"]').setValue('伏笔分析')
  await modal().get('textarea').setValue('先分析伏笔')
  await modal().get('form').trigger('submit')
  await flushPromises()
  expect(skillsApi.create).toHaveBeenCalledWith({ task: 'story', name: '伏笔分析', description: '', instructions: '先分析伏笔', references: [], is_active: true })
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([6])
  expect(wrapper.find('form').exists()).toBe(false)
  expect(document.querySelector('dialog[open]')).toBeNull()
  expect(wrapper.get('[role="status"]').text()).toContain('技能已保存')
})

it('saves the current version and retains edits when saving fails', async () => {
  const wrapper = mount(TaskSkillPicker, { props: { task: 'story', modelValue: 5 } })
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '编辑技能')!.trigger('click')
  await modal().get('textarea').setValue('尚未保存的方法')
  vi.mocked(skillsApi.update).mockRejectedValueOnce(new Error('保存失败，请重试'))
  await modal().get('form').trigger('submit')
  await flushPromises()
  expect(skillsApi.update).toHaveBeenCalledWith(5, expect.objectContaining({ instructions: '尚未保存的方法' }), 2)
  expect(modal().get('[role="alert"]').text()).toContain('保存失败')
  expect(modal().get('textarea').element).toHaveValue('尚未保存的方法')
  await modal().findAll('button').find(button => button.text() === '取消')!.trigger('click')
  expect(document.querySelector('dialog[open]')).toBeNull()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
})

it('keeps the dialog open while saving and clears editing state on native close', async () => {
  let complete!: (value: Awaited<ReturnType<typeof skillsApi.update>>) => void
  vi.mocked(skillsApi.update).mockImplementation(() => new Promise(resolve => { complete = resolve }))
  const wrapper = mount(TaskSkillPicker, { props: { task: 'story', modelValue: 5 } })
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '编辑技能')!.trigger('click')
  const panel = modal()
  await panel.get('form').trigger('submit')
  const cancel = new Event('cancel', { cancelable: true })
  panel.element.dispatchEvent(cancel)
  expect(cancel.defaultPrevented).toBe(true)
  expect(panel.element.open).toBe(true)
  expect(panel.get('button[aria-label="关闭"]').attributes('disabled')).toBeDefined()
  complete({ code: 0, message: '', data: { ...custom, version: 3 } })
  await flushPromises()
  expect(document.querySelector('dialog[open]')).toBeNull()
  expect(wrapper.emitted('editing-change')?.at(-1)).toEqual([false])
})

it('persists the default without starting generation', async () => {
  const wrapper = mount(TaskSkillPicker, { props: { task: 'story', modelValue: 5 } })
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '设为默认')!.trigger('click')
  await flushPromises()
  expect(skillsApi.setDefault).toHaveBeenCalledWith('story', 5)
  expect(wrapper.get('[role="status"]').text()).toContain('默认技能')
})

it('offers retry after loading failure and disables editing during generation', async () => {
  vi.mocked(skillsApi.list).mockRejectedValueOnce(new Error('无法读取技能'))
  const wrapper = mount(TaskSkillPicker, { props: { task: 'story', modelValue: 0, disabled: true } })
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('无法读取技能')
  await wrapper.findAll('button').find(button => button.text() === '重试')!.trigger('click')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  expect(wrapper.get('button[aria-label="故事分析技能"]').attributes('disabled')).toBeDefined()
  expect(wrapper.findAll('button').find(button => button.text() === '复制并编辑')!.attributes('disabled')).toBeDefined()
})

it.each([['screenplay', '剧本改编技能'], ['assets', '资产提取技能'], ['storyboard', '分镜生成技能']] as const)('uses the shared modal and a separate skill collection for %s', async (task, title) => {
  vi.mocked(skillsApi.list).mockResolvedValue({ code: 0, message: '', data: { items: [{ ...builtin, task }], default_skill_id: 0 } })
  const wrapper = mount(TaskSkillPicker, { props: { task, modelValue: 0 } })
  await flushPromises()
  expect(skillsApi.list).toHaveBeenCalledWith(task)
  expect(wrapper.get('.skill-label').text()).toBe(title)
  expect(wrapper.find(`button[aria-label="${title}"]`).exists()).toBe(true)
  await wrapper.findAll('button').find(button => button.text() === '复制并编辑')!.trigger('click')
  await modal().get('form').trigger('submit')
  await flushPromises()
  expect(skillsApi.create).toHaveBeenCalledWith(expect.objectContaining({ task }))
})
