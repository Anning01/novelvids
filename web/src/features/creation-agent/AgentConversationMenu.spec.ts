import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AgentConversationMenu from './AgentConversationMenu.vue'

const rows = [
  { id: 1, novel_id: 7, title: '在雨夜车站补充一个独立完整的空镜，保持人物外貌与服装一致', active_task_id: null, created_at: '', updated_at: '2026-09-10T12:30:00Z' },
  { id: 2, novel_id: 7, title: '咖啡馆晨光', active_task_id: null, created_at: '', updated_at: '2026-09-09T08:20:00Z' },
]
const Popover = defineComponent({ props: ['visible', 'disabled'], emits: ['update:visible'],
  template: `<div><div @click="$emit('update:visible', !visible)"><slot name="reference" /></div><slot v-if="visible" /></div>` })
function setup() {
  return mount(AgentConversationMenu, { props: { conversations: rows, deletedConversations: [], currentId: 1, disabled: false },
    global: { stubs: { ElPopover: Popover } } })
}

describe('会话列表', () => {
  it('keeps an open list visible while an operation disables its controls', async () => {
    const wrapper = setup()
    await wrapper.get('[aria-label="对话记录"]').trigger('click')
    await wrapper.setProps({ disabled: true })
    expect(wrapper.getComponent(Popover).props('disabled')).toBe(false)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(wrapper.get('[aria-label="删除会话：咖啡馆晨光"]').attributes('disabled')).toBeDefined()
  })

  it('keeps the current title and new-session action separate; filters and selects history', async () => {
    const wrapper = setup()
    expect(wrapper.get('[aria-label="对话记录"]').text()).toContain(rows[0]!.title)
    expect(wrapper.get('[aria-label="新建对话"]').text()).toBe('新会话')
    await wrapper.get('[aria-label="对话记录"]').trigger('click')
    expect(wrapper.get('[aria-current="true"]').text()).toContain('当前会话')
    await wrapper.get('input[aria-label="搜索会话"]').setValue('晨光')
    expect(wrapper.findAll('li')).toHaveLength(1)
    await wrapper.get('[aria-label="打开会话：咖啡馆晨光"]').trigger('click')
    expect(wrapper.emitted('select')).toEqual([[2]])
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    await wrapper.get('[aria-label="新建对话"]').trigger('click')
    expect(wrapper.emitted('create')).toHaveLength(1)
  })

  it('does not select a row when deleting and supports cancelling the inline confirmation', async () => {
    const wrapper = setup()
    await wrapper.get('[aria-label="对话记录"]').trigger('click')
    await wrapper.get('[aria-label="删除会话：咖啡馆晨光"]').trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
    expect(wrapper.get('[aria-label="确认删除会话"]').text()).toContain('设定与分镜会保留')
    await wrapper.findAll('button').find(b => b.text() === '取消')!.trigger('click')
    expect(wrapper.emitted('delete')).toBeUndefined()
    await wrapper.get('[aria-label="删除会话：咖啡馆晨光"]').trigger('click')
    await wrapper.findAll('button').find(b => b.text() === '删除会话')!.trigger('click')
    expect(wrapper.emitted('delete')).toEqual([[2]])
    await wrapper.setProps({ conversations: [rows[0]!] })
    expect(wrapper.find('[aria-label="确认删除会话"]').exists()).toBe(false)
  })

  it('offers restoration in deleted history, and Escape closes only the history popup', async () => {
    const wrapper = setup()
    await wrapper.setProps({ deletedConversations: [rows[1]!] })
    await wrapper.get('[aria-label="对话记录"]').trigger('click')
    await wrapper.findAll('button').find(b => b.text() === '已删除')!.trigger('click')
    expect(wrapper.emitted('loadDeleted')).toHaveLength(1)
    await wrapper.get('[aria-label="恢复会话：咖啡馆晨光"]').trigger('click')
    expect(wrapper.emitted('restore')).toEqual([[2]])
    await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
})
