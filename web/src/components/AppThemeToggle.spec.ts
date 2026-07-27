import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import { createAppThemeController, appThemeControllerKey } from '@/shared/appTheme'
import AppThemeToggle from './AppThemeToggle.vue'

it('offers system, light, and dark choices and applies the selected preference', async () => {
  window.localStorage.clear()
  const root = document.createElement('html')
  const theme = createAppThemeController({
    root,
    storage: window.localStorage,
    media: {
      matches: false,
      media: '(prefers-color-scheme: dark)',
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => true,
    },
  })
  const wrapper = mount(AppThemeToggle, {
    global: { provide: { [appThemeControllerKey as symbol]: theme } },
  })

  await wrapper.get('[aria-label^="外观主题"]').trigger('click')
  expect(wrapper.get('[role="menu"]').findAll('[role="menuitemradio"]')).toHaveLength(3)
  await wrapper.get('[data-theme-preference="dark"]').trigger('click')

  expect(theme.preference.value).toBe('dark')
  expect(root.dataset.appTheme).toBe('dark')
  expect(wrapper.get('[aria-label^="外观主题"]').attributes('aria-label')).toContain('深色')
})

it('shows a discoverable label in the sidebar placement', () => {
  const wrapper = mount(AppThemeToggle, {
    props: { placement: 'sidebar' },
  })

  expect(wrapper.get('.app-theme-toggle__label').text()).toContain('外观')
  expect(wrapper.get('.app-theme-toggle').classes()).toContain('is-sidebar')
})
