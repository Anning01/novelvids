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

function mockSourceEditor(undoValue?: string) {
  class SourceEditor {
    field: HTMLTextAreaElement
    constructor(element: HTMLElement, private options: IOptions) {
      this.field = document.createElement('textarea')
      this.field.value = options.value ?? ''
      this.field.addEventListener('input', () => options.input?.(this.getValue()))
      this.field.addEventListener('keydown', event => {
        if ((event.ctrlKey || event.metaKey) && event.key === 'z' && undoValue !== undefined) {
          this.field.value = undoValue
          options.input?.(this.getValue())
        }
      })
      element.append(this.field)
      queueMicrotask(() => options.after?.())
    }
    getValue() { return this.field.value.endsWith('\n') ? this.field.value : `${this.field.value}\n` }
    setValue(value: string) { this.field.value = value }
    updateValue(value: string) {
      this.field.setRangeText(value, this.field.selectionStart, this.field.selectionEnd, 'end')
      this.field.focus()
      this.options.input?.(this.getValue())
    }
    setTheme() {}
    destroy() { this.field.remove() }
  }
  vi.mocked(loadVditor).mockResolvedValue(SourceEditor as unknown as Awaited<ReturnType<typeof loadVditor>>)
}

it('inserts fixed variables from buttons and keeps source Markdown editing available', async () => {
  mockSourceEditor()
  const wrapper = mount(SkillMarkdownEditor, { props: { modelValue: '参考 ', task: 'screenplay' }, attachTo: document.body })
  await flushPromises()
  const field = wrapper.get('textarea').element
  field.setSelectionRange(0, field.value.length)
  await wrapper.findAll('button').find(button => button.text() === '参考时长')!.trigger('click')
  expect(field.value).toBe('参考 {{max_seconds}}')
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['参考 {{max_seconds}}\n'])
  expect(wrapper.text()).toContain('不能修改名称')
  wrapper.unmount()
})

it('rejects non-cancelable partial edits and preserves surrounding text', async () => {
  mockSourceEditor()
  const original = '正文 {{input}} 结尾'
  const wrapper = mount(SkillMarkdownEditor, { props: { modelValue: original }, attachTo: document.body })
  await flushPromises()
  const field = wrapper.get('textarea').element
  field.value = '正文 {{inpu}} 结尾'
  await wrapper.get('textarea').trigger('input')
  expect(field.value).toBe(original)
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  expect(wrapper.get('[role="status"]').text()).toContain('不可拆改')
  wrapper.unmount()
})

it('selects and removes a whole placeholder with Backspace instead of breaking its syntax', async () => {
  mockSourceEditor()
  const wrapper = mount(SkillMarkdownEditor, { props: { modelValue: 'A{{input}}B' }, attachTo: document.body })
  await flushPromises()
  const field = wrapper.get('textarea').element
  field.focus()
  field.setSelectionRange(10, 10)
  await wrapper.get('textarea').trigger('keydown', { key: 'Backspace' })
  expect([field.selectionStart, field.selectionEnd]).toEqual([1, 10])
  field.setRangeText('', field.selectionStart, field.selectionEnd, 'end')
  await wrapper.get('textarea').trigger('input')
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['AB\n'])
  wrapper.unmount()
})

it('prevents source-mode shortcuts from opening an unprotected editing surface', async () => {
  mockSourceEditor()
  const wrapper = mount(SkillMarkdownEditor, { props: { modelValue: '{{input}}' } })
  await flushPromises()
  const event = new KeyboardEvent('keydown', { key: '8', code: 'Digit8', ctrlKey: true, altKey: true, cancelable: true, bubbles: true })
  wrapper.get('textarea').element.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
  wrapper.unmount()
})

it('restores complete adjacent placeholders through editor undo even after the caret moved', async () => {
  mockSourceEditor('{{input}}{{language}}')
  const wrapper = mount(SkillMarkdownEditor, { props: { modelValue: '{{language}}' }, attachTo: document.body })
  await flushPromises()
  const field = wrapper.get('textarea').element
  field.focus()
  field.setSelectionRange(field.value.length, field.value.length)
  await wrapper.get('textarea').trigger('keydown', { key: 'z', metaKey: true })
  expect(field.value).toBe('{{input}}{{language}}')
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['{{input}}{{language}}\n'])
  wrapper.unmount()
})
