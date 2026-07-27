import { expect, it, vi } from 'vitest'
import { createAppThemeController } from './appTheme'

function createEnvironment(initialDark: boolean, storedPreference?: string) {
  let listener: ((event: MediaQueryListEvent) => void) | undefined
  const values = new Map<string, string>()
  if (storedPreference) values.set('novel-vids-theme', storedPreference)

  const storage = {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => { values.set(key, value) }),
    removeItem: vi.fn((key: string) => { values.delete(key) }),
    clear: vi.fn(() => values.clear()),
    key: vi.fn(() => null),
    get length() { return values.size },
  } satisfies Storage
  const root = document.createElement('html')
  const media = {
    matches: initialDark,
    media: '(prefers-color-scheme: dark)',
    onchange: null,
    addEventListener: vi.fn((_type: string, callback: EventListenerOrEventListenerObject) => {
      listener = callback as (event: MediaQueryListEvent) => void
    }),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  } satisfies MediaQueryList

  return {
    media,
    root,
    storage,
    emitSystemTheme(dark: boolean) {
      Object.defineProperty(media, 'matches', { configurable: true, value: dark })
      listener?.({ matches: dark } as MediaQueryListEvent)
    },
  }
}

it('follows the system theme until a manual preference is chosen', () => {
  const environment = createEnvironment(true)
  const theme = createAppThemeController(environment)

  expect(theme.preference.value).toBe('system')
  expect(theme.resolvedTheme.value).toBe('dark')
  expect(environment.root.dataset.appTheme).toBe('dark')

  environment.emitSystemTheme(false)
  expect(theme.resolvedTheme.value).toBe('light')
  expect(environment.root.dataset.appTheme).toBe('light')
})

it('persists a manual theme and ignores later system changes', () => {
  const environment = createEnvironment(false)
  const theme = createAppThemeController(environment)

  theme.setPreference('dark')
  environment.emitSystemTheme(false)

  expect(theme.preference.value).toBe('dark')
  expect(theme.resolvedTheme.value).toBe('dark')
  expect(environment.root.dataset.appTheme).toBe('dark')
  expect(environment.storage.setItem).toHaveBeenCalledWith('novel-vids-theme', 'dark')
})

it('can return from a manual override to live system following', () => {
  const environment = createEnvironment(false, 'dark')
  const theme = createAppThemeController(environment)

  theme.setPreference('system')
  environment.emitSystemTheme(true)

  expect(theme.preference.value).toBe('system')
  expect(theme.resolvedTheme.value).toBe('dark')
  expect(environment.root.dataset.appTheme).toBe('dark')
})
