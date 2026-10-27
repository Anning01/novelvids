import { expect, it } from 'vitest'
import { setLocale } from '@/i18n'
import { projectRuntime } from './projectOverview'

it('keeps real zero distinct from unconfirmed actual runtime and uses exact short durations', () => {
  setLocale('zh')
  expect(projectRuntime(0)).toEqual({ value: '0', unit: '分钟', incomplete: false })
  expect(projectRuntime(0, 2)).toEqual({ value: '待确认', unit: '', incomplete: true })
  expect(projectRuntime(35)).toEqual({ value: '35', unit: '秒', incomplete: false })
  expect(projectRuntime(120, 1)).toEqual({ value: '≥ 2', unit: '分钟', incomplete: true })
  setLocale('en')
  expect(projectRuntime(120).unit).toBe('min')
})
