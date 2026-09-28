import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'
import catalog from './messages.json'
import { applySavedLocale, dateLocale, elementLocale, locale, LOCALE_CACHE_KEY, refreshLocale, setLocale, tr } from './index'
import AppThemeToggle from '@/components/AppThemeToggle.vue'

const reply = (value: unknown) => ({ ok: true, json: async () => ({ code: 0, data: { locale: value } }) })
afterEach(() => { vi.unstubAllGlobals(); localStorage.removeItem(LOCALE_CACHE_KEY) })

describe('application language', () => {
  it('switches rendered copy, component locale and document metadata without replacing drafts', async () => {
    const page = mount(defineComponent({
      setup: () => ({ tr, draft: ref('Alex 陈: Keep my words.') }),
      template: '<div><h1>{{ tr("系统语言") }}</h1><input v-model="draft"></div>',
    }))
    const input = page.get('input').element
    setLocale('en')
    await nextTick()
    expect(page.text()).toBe('System language')
    expect(page.get('input').element).toBe(input)
    expect(input.value).toBe('Alex 陈: Keep my words.')
    expect(elementLocale.value.name).toBe('en')
    expect(dateLocale.value).toBe('en-US')
    expect(document.documentElement.lang).toBe('en')
    setLocale('zh')
    await nextTick()
    expect(page.text()).toBe('系统语言')
    expect(input.value).toBe('Alex 陈: Keep my words.')
  })

  it('keeps option labels reactive in an already mounted component', async () => {
    const wrapper = mount(AppThemeToggle, { props: { placement: 'sidebar' } })
    expect(wrapper.text()).toContain('外观')
    setLocale('en')
    await nextTick()
    expect(wrapper.text()).toContain('Appearance')
    expect(wrapper.text()).not.toContain('外观')
  })

  it('loads only the public locale endpoint and caches a valid response', async () => {
    const fetch = vi.fn().mockResolvedValue(reply('en'))
    vi.stubGlobal('fetch', fetch)
    await refreshLocale()
    expect(fetch.mock.calls[0]?.[0]).toBe('/api/config/locale')
    expect(locale.value).toBe('en')
    expect(localStorage.getItem(LOCALE_CACHE_KEY)).toBe('en')
  })

  it('retains the last known locale during network and invalid-response failures', async () => {
    setLocale('zh')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(reply('fr')))
    await refreshLocale()
    await refreshLocale()
    expect(locale.value).toBe('zh')
  })

  it('does not let a stale response overwrite an explicit save', async () => {
    let resolve: (value: ReturnType<typeof reply>) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise(done => { resolve = done })))
    const pending = refreshLocale()
    applySavedLocale('en')
    resolve(reply('zh'))
    await pending
    expect(locale.value).toBe('en')
  })

  it('interpolates user content literally without treating it as message syntax', () => {
    setLocale('en')
    expect(tr('删除「{p0}」？', { p0: '@{陈 Alex} | {p1}' })).toBe('Delete “@{陈 Alex} | {p1}”?')
  })

  it('has complete English messages with matching interpolation parameters', () => {
    const parameters = (value: string) => [...value.matchAll(/\{p\d+\}/g)].map(match => match[0]).sort()
    for (const entries of Object.values(catalog)) {
      for (const [source, translated] of Object.entries(entries)) {
        expect(translated.trim(), source).not.toBe('')
        expect(parameters(translated), source).toEqual(parameters(source))
      }
    }
  })
})
