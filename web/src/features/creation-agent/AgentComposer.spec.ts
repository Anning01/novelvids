import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import AgentComposer from './AgentComposer.vue'

vi.mock('vue-element-plus-x', () => ({ XSender: defineComponent({
  props: ['disabled'], emits: ['change', 'submit', 'cancel'],
  setup(_, { emit, expose }) {
    const text = ref('')
    const editor = {
      async reset(options: { chatNode: { type: 'Write'; text: string }[][] }) {
        text.value = ''; emit('change')
        await Promise.resolve()
        text.value = options.chatNode.map(line => line.map(node => node.text).join('')).join('\n')
        emit('change')
      },
    }
    expose({ getSender: () => editor, getModelValue: () => ({ text: text.value }),
      // XSender inserts at the caret; setText is not a replacement operation.
      setText: (value: string) => { text.value += value; emit('change') }, focus: vi.fn() })
    function input(event: Event) { text.value = (event.target as HTMLElement).textContent ?? ''; emit('change') }
    return { text, input }
  },
  template: `<div><div :contenteditable="!disabled" @input="input" @keydown.enter.prevent="$emit('submit')">{{ text }}</div><slot name="action-list"/><slot name="footer"/></div>`,
}) }))

it('restores an existing draft into the editor and emits text changes for persistence', async () => {
  const wrapper = mount(AgentComposer, { props: { modelValue: '保留人物的灰色风衣', modelId: '1', models: [{ id: 1, name: '助手模型', model: 'model' }], disabled: false, busy: false, submitting: false } })
  await flushPromises()
  const editor = wrapper.get('[role="textbox"]')
  expect(editor.text()).toBe('保留人物的灰色风衣')
  await wrapper.setProps({ modelValue: '另一会话的草稿' })
  await flushPromises()
  expect(editor.text()).toBe('另一会话的草稿')
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  editor.element.textContent = '再让光线柔和一些'
  await editor.trigger('input')
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['再让光线柔和一些'])
  wrapper.unmount()
})

it('clears accepted input and uses the latest draft when conversation changes during reset', async () => {
  const wrapper = mount(AgentComposer, { props: { modelValue: '已经发送的要求', modelId: '1', models: [], disabled: false, busy: false, submitting: false } })
  await flushPromises()
  await wrapper.setProps({ modelValue: '', busy: true })
  await flushPromises()
  expect(wrapper.get('[role="textbox"]').text()).toBe('')
  await wrapper.setProps({ modelValue: '第一份草稿' })
  await wrapper.setProps({ modelValue: '最新草稿\n保持人物服装' })
  await flushPromises()
  expect(wrapper.get('[role="textbox"]').text()).toBe('最新草稿\n保持人物服装')
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  wrapper.unmount()
})

it('disables empty submission and exposes a stop action while running', async () => {
  const wrapper = mount(AgentComposer, { props: { modelValue: '  ', modelId: '1', models: [], disabled: false, busy: false, submitting: false } })
  await flushPromises()
  expect(wrapper.get('[aria-label="发送创作要求"]').attributes('disabled')).toBeDefined()
  await wrapper.get('[role="textbox"]').trigger('keydown', { key: 'Enter' })
  expect(wrapper.emitted('submit')).toBeUndefined()
  await wrapper.setProps({ modelValue: '光线柔和一些' })
  await wrapper.get('[aria-label="发送创作要求"]').trigger('click')
  expect(wrapper.emitted('submit')).toEqual([['光线柔和一些']])
  await wrapper.setProps({ busy: true })
  await wrapper.get('[aria-label="停止创作助手"]').trigger('click')
  expect(wrapper.emitted('stop')).toHaveLength(1)
  expect(wrapper.find('[aria-label="发送创作要求"]').exists()).toBe(false)
  wrapper.unmount()
})
