import { computed } from 'vue'
import { createI18n, type MessageContext } from 'vue-i18n'
import en from 'element-plus/es/locale/lang/en'
import zh from 'element-plus/es/locale/lang/zh-cn'
import catalog from './messages.json'

export type AppLocale = 'zh' | 'en'
export const LOCALE_CACHE_KEY = 'novelvids_locale'
const isLocale = (value: unknown): value is AppLocale => value === 'zh' || value === 'en'
function cachedLocale(): AppLocale {
  try {
    const value = localStorage.getItem(LOCALE_CACHE_KEY)
    return isLocale(value) ? value : 'en'
  } catch { return 'en' }
}
// Source messages are stable keys. Functions preserve literal @, | and braces in
// examples; only explicitly named p0/p1 parameters are interpolated.
function message(text: string) {
  return (ctx: MessageContext) => text.replace(/\{(p\d+)\}/g, (_, key: string) => String(ctx.named(key)))
}
const sourceKeys = new Map<string, string>()
const messages: Record<AppLocale, Record<string, ReturnType<typeof message>>> = { zh: {}, en: {} }
for (const [group, entries] of Object.entries(catalog)) {
  for (const [index, [source, english]] of Object.entries(entries).entries()) {
    const key = `${group}_${index}`
    sourceKeys.set(source, key)
    messages.zh[key] = message(source)
    messages.en[key] = message(english)
  }
}
export const i18n = createI18n({ legacy: false, locale: cachedLocale(), fallbackLocale: 'en', messages })
export const locale = i18n.global.locale
export const dateLocale = computed(() => locale.value === 'zh' ? 'zh-CN' : 'en-US')
export const elementLocale = computed(() => locale.value === 'zh' ? zh : en)
export function tr(source: string, parameters: Record<string, unknown> = {}): string {
  const key = sourceKeys.get(source)
  // Read locale even for untranslated legacy labels so rendering stays reactive.
  void locale.value
  return key ? i18n.global.t(key, parameters) : source.replace(/\{(p\d+)\}/g, (_, name: string) => String(parameters[name] ?? ''))
}
export function setLocale(value: AppLocale): void {
  locale.value = value
  document.documentElement.lang = value === 'zh' ? 'zh-CN' : 'en'
  document.title = value === 'zh' ? '猫影短剧 | Cat Shadow Studio' : 'NovelVids | Short drama studio'
  try { localStorage.setItem(LOCALE_CACHE_KEY, value) } catch { /* Storage may be disabled. */ }
}
let revision = 0
export async function refreshLocale(): Promise<void> {
  const requestRevision = ++revision
  try {
    const base = ((import.meta.env.VITE_API_BASE ?? '') as string).replace(/\/+$/, '')
    const response = await fetch(`${base}/api/config/locale`, { signal: AbortSignal.timeout(5000), cache: 'no-store' })
    if (!response.ok) return
    const payload = await response.json()
    if (requestRevision === revision && payload.code === 0 && isLocale(payload.data?.locale)) setLocale(payload.data.locale)
  } catch { /* Keep the last known language during network failures. */ }
}
export function applySavedLocale(value: AppLocale): void {
  ++revision // An older in-flight refresh cannot undo an explicit save.
  setLocale(value)
}
export async function initializeLocale(): Promise<void> {
  setLocale(cachedLocale())
  await refreshLocale()
  window.addEventListener('focus', () => { void refreshLocale() })
}
