import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { expect, it } from 'vitest'
import SectionNode from './SectionNode.vue'

it('keeps existing group descriptions in the draggable heading, including after selection changes', async () => {
  const description = '四个镜头的参考资料。'.repeat(30)
  const wrapper = mount(SectionNode, {
    props: {
      id: 'section-7', type: 'section', selected: false, connectable: true,
      data: { title: '镜头组', description, node_keys: ['a', 'b', 'c', 'd'] },
    } as never,
    global: { plugins: [createPinia()], stubs: { ElPopover: true, WorkbenchColorPicker: true } },
  })
  const header = wrapper.get('header')
  expect(header.get('.workbench-group-summary').attributes('title')).toBe(description)
  expect(header.get('.workbench-group-count').text()).toContain('4')
  expect(wrapper.find('section > p').exists()).toBe(false)
  await wrapper.setProps({ selected: true })
  expect(header.find('[role="toolbar"]').exists()).toBe(true)
  expect(header.get('.workbench-group-summary').text()).toBe(description)
  wrapper.unmount()
})
