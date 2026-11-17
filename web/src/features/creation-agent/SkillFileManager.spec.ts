import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import SkillFileManager from './SkillFileManager.vue'
import { packageLimits, skillEntry } from '@/test/skillPackageFixture'
import type { SkillFile } from './skillsApi'

vi.mock('./SkillMarkdownEditor.vue', () => ({ default: { props: ['modelValue'], emits: ['update:modelValue'], template: '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' } }))

function render() {
  const files: SkillFile[] = [{ path: 'SKILL.md', content: skillEntry('Read [method](references/method.md)'), encoding: 'utf-8' },
    { path: 'references/method.md', content: 'original method', encoding: 'utf-8' }]
  const wrapper = mount(SkillFileManager, { props: { modelValue: files, task: 'screenplay', limits: packageLimits,
    'onUpdate:modelValue': value => { void wrapper.setProps({ modelValue: value }) } } })
  return wrapper
}
it('edits files independently and retains unsaved contents while switching', async () => {
  const wrapper = render()
  await wrapper.get('button[title="references/method.md"]').trigger('click')
  await wrapper.get('textarea').setValue('updated method')
  await wrapper.get('button[title="SKILL.md"]').trigger('click')
  expect(wrapper.get('textarea').element.value).toContain('name: test-skill')
  await wrapper.get('button[title="references/method.md"]').trigger('click')
  expect(wrapper.get('textarea').element.value).toBe('updated method')
  expect(wrapper.text()).not.toContain('参考资料')
  wrapper.unmount()
})
it('adds a nested file, rejects traversal, and keeps SKILL.md protected', async () => {
  const wrapper = render()
  expect(wrapper.get('button[aria-label="移除文件"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('button[aria-label="重命名文件"]').attributes('disabled')).toBeDefined()
  await wrapper.get('button[aria-label="新建文件"]').trigger('click')
  await wrapper.get('.file-path-form input').setValue('../outside.md')
  await wrapper.get('.file-path-form input').trigger('keydown', { key: 'Enter' })
  expect(wrapper.get('[role="alert"]').text()).toContain('相对路径')
  await wrapper.get('.file-path-form input').setValue('assets/template.txt')
  await wrapper.get('.file-path-form input').trigger('keydown', { key: 'Enter' })
  await flushPromises()
  expect(wrapper.find('button[title="assets/template.txt"]').exists()).toBe(true)
  await wrapper.get('button[aria-label="移除文件"]').trigger('click')
  await wrapper.get('button[aria-label="移除文件"]').trigger('click')
  expect(wrapper.find('button[title="assets/template.txt"]').exists()).toBe(true)
  await wrapper.findAll('button').find(button => button.text() === '确认移除')!.trigger('click')
  await flushPromises()
  expect(wrapper.find('button[title="assets/template.txt"]').exists()).toBe(false)
  wrapper.unmount()
})

it('does not create a file when Enter confirms a Chinese IME candidate', async () => {
  const wrapper = render()
  await wrapper.get('button[aria-label="新建文件"]').trigger('click')
  const input = wrapper.get('.file-path-form input')
  await input.setValue('references/角色.md')
  await input.trigger('keydown', { key: 'Enter', isComposing: true, keyCode: 229 })
  expect(wrapper.find('button[title="references/角色.md"]').exists()).toBe(false)
  expect(wrapper.find('.file-path-form').exists()).toBe(true)
  await input.trigger('keydown', { key: 'Enter', isComposing: false, keyCode: 13 })
  await flushPromises()
  expect(wrapper.find('button[title="references/角色.md"]').exists()).toBe(true)
  wrapper.unmount()
})
