import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import SkillMarkdownEditor from './SkillMarkdownEditor.vue'
import { loadVditor } from './vditorLoader'

vi.mock('./vditorLoader', () => ({ loadVditor: vi.fn() }))

it('preserves the original Markdown until a real edit and releases the editor on close', async () => {
  let options: IOptions = {}
  let content = '# Heading\n\n{{input}}\n'
  const destroy = vi.fn()
  class Editor {
    constructor(_element: HTMLElement, config: IOptions) {
      options = config
      queueMicrotask(() => config.after?.())
    }
    getValue() { return content }
    setValue(value: string) { content = value }
    setTheme() {}
    destroy = destroy
  }
  vi.mocked(loadVditor).mockResolvedValue(Editor as unknown as Awaited<ReturnType<typeof loadVditor>>)
  const original = '# Heading\n{{input}}\n'
  const wrapper = mount(SkillMarkdownEditor, { props: { modelValue: original } })
  await flushPromises()
  options.input?.(content)
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  content += '\nNew text  \n'
  options.input?.(content)
  expect(wrapper.emitted('update:modelValue')).toEqual([[content]])
  wrapper.unmount()
  expect(destroy).toHaveBeenCalledOnce()
})

it('retains an editable source field if rich editor resources fail', async () => {
  vi.mocked(loadVditor).mockRejectedValueOnce(new Error('offline'))
  const source = '---\nname: test\n---\n```json\n{{input}}\n```\n'
  const wrapper = mount(SkillMarkdownEditor, { props: { modelValue: source } })
  await flushPromises()
  expect(wrapper.get('textarea').element.value).toBe(source)
  await wrapper.get('textarea').setValue(`${source}Changed\n`)
  expect(wrapper.emitted('update:modelValue')).toEqual([[`${source}Changed\n`]])
  wrapper.unmount()
})
