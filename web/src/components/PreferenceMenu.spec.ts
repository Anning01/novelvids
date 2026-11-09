import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { expect, it } from 'vitest'
import PreferenceMenu from './PreferenceMenu.vue'

function render(disabled = false) {
  return mount(PreferenceMenu, { attachTo: document.body, props: {
    label: 'Preferences', modelValue: 'first', disabled,
    options: [{ value: 'first', label: 'First' }, { value: 'second', label: 'Second' }],
  }, slots: { trigger: '<template #default="{ toggle, open }"><button :aria-expanded="open" @click="toggle">Open</button></template>' } })
}

it('shares compact option rows and applies a keyboard selection without a save step', async () => {
  const wrapper = render()
  await wrapper.get('button').trigger('click')
  await flushPromises()
  const options = wrapper.findAll('[role="menuitemradio"]')
  expect(options.map(option => option.text())).toEqual(['First', 'Second'])
  expect(document.activeElement).toBe(options[0]!.element)
  await wrapper.get('[role="menu"]').trigger('keydown', { key: 'ArrowDown' })
  expect(document.activeElement).toBe(options[1]!.element)
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  await wrapper.get('[role="menu"]').trigger('keydown', { key: 'Enter' })
  expect(wrapper.emitted('update:modelValue')).toEqual([['second']])
  expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  expect(document.activeElement).toBe(wrapper.get('button').element)
})

it('keeps read-only choices disabled and supports Escape without changing a preference', async () => {
  const wrapper = render(true)
  await wrapper.get('button').trigger('click')
  expect(wrapper.findAll('[role="menuitemradio"]').every(option => option.attributes('disabled') !== undefined)).toBe(true)
  await wrapper.get('[role="menu"]').trigger('keydown', { key: 'Escape' })
  expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
})

it('closes the first preference menu when another is opened', async () => {
  const wrapper = mount(defineComponent({ components: { PreferenceMenu },
    template: `<div><PreferenceMenu v-for="name in ['Language','Appearance']" :key="name" :label="name" model-value="a" :options="[{value:'a',label:'A'}]">
      <template #trigger="{toggle}"><button @click="toggle">{{name}}</button></template>
    </PreferenceMenu></div>`,
  }), { attachTo: document.body })
  await wrapper.get('button').trigger('click')
  expect(wrapper.get('[role="menu"]').attributes('aria-label')).toBe('Language')
  await wrapper.findAll('.preference-menu > button')[1]!.trigger('click')
  expect(wrapper.findAll('[role="menu"]')).toHaveLength(1)
  expect(wrapper.get('[role="menu"]').attributes('aria-label')).toBe('Appearance')
})
