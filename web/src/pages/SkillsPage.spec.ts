import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import SkillsPage from './SkillsPage.vue'
import { skillsApi, type CreativeSkill } from '@/features/creation-agent/skillsApi'

vi.mock('@/features/creation-agent/skillsApi', () => ({ skillsApi: { list: vi.fn(), setActive: vi.fn(), importArchive: vi.fn(), setDefault: vi.fn() } }))
vi.mock('@/features/creation-agent/SkillEditorDialog.vue', () => ({ default: { props: ['source', 'task'], template: '<div class="editor-stub">{{ task }} {{ source?.name }}</div>' } }))
const builtin: CreativeSkill = { id: 0, task: 'story', name: '故事分析', description: '内置方法', instructions: '# 方法', references: [], builtin: true, is_active: true }
const custom: CreativeSkill = { ...builtin, id: 3, version: 2, name: '悬疑', description: '关注伏笔', builtin: false }
let wrapper: ReturnType<typeof mount>
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(skillsApi.list).mockResolvedValue({ code: 0, message: '', data: { items: [builtin, custom], default_skill_id: 3 } })
  vi.mocked(skillsApi.setActive).mockResolvedValue({ code: 0, message: '', data: { ...custom, version: 3, is_active: false } })
})
afterEach(() => wrapper?.unmount())
it('searches skills and switches to cards without hiding row operations', async () => {
  wrapper = mount(SkillsPage)
  await flushPromises()
  expect(wrapper.findAll('tbody tr')).toHaveLength(2)
  await wrapper.get('input[type="search"]').setValue('伏笔')
  expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  await wrapper.get('button[aria-label="卡片视图"]').trigger('click')
  expect(wrapper.findAll('.skills-cards li')).toHaveLength(1)
  await wrapper.findAll('button').find(button => button.text() === '编辑与调试')!.trigger('click')
  expect(wrapper.get('.editor-stub').text()).toContain('悬疑')
})
it('disables the default skill with version checking and restores the builtin default', async () => {
  wrapper = mount(SkillsPage)
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '停用')!.trigger('click')
  await flushPromises()
  expect(skillsApi.setActive).toHaveBeenCalledWith(3, false, 2)
  expect(wrapper.get('tbody tr:first-child .default-tag').text()).toBe('默认')
  expect(wrapper.get('[role="status"]').text()).toContain('停用')
})
it('loads each tab separately and does not show an old response after switching', async () => {
  let complete!: (value: Awaited<ReturnType<typeof skillsApi.list>>) => void
  vi.mocked(skillsApi.list).mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
  wrapper = mount(SkillsPage)
  await wrapper.findAll('.task-tabs button')[1]!.trigger('click')
  await flushPromises()
  complete({ code: 0, message: '', data: { items: [], default_skill_id: 0 } })
  await flushPromises()
  expect(skillsApi.list).toHaveBeenLastCalledWith('screenplay')
  expect(wrapper.findAll('tbody tr')).toHaveLength(2)
})
