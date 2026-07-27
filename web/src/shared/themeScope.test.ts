import { expect, it } from 'vitest'
import { isWorkflowThemeSurface } from './themeScope'

it('isolates wireless and legacy workflows from the external app theme', () => {
  expect(isWorkflowThemeSurface({
    name: 'short-drama-storyboard',
    path: '/create/short-drama/storyboard/9',
    view: 'workflow',
  })).toBe(true)
  expect(isWorkflowThemeSurface({
    path: '/novel/9/chapter/2162/step/3',
  })).toBe(true)
})

it('keeps the theme control available on the external storyboard view', () => {
  expect(isWorkflowThemeSurface({
    name: 'short-drama-storyboard',
    path: '/create/short-drama/storyboard/9',
  })).toBe(false)
})
