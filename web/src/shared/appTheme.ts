import { computed, ref, type ComputedRef, type InjectionKey, type Ref } from 'vue'

export type AppTheme = 'light' | 'dark'
export type AppThemePreference = 'system' | AppTheme

export interface AppThemeController {
  preference: Ref<AppThemePreference>
  resolvedTheme: ComputedRef<AppTheme>
  setPreference: (preference: AppThemePreference) => void
  destroy: () => void
}

interface AppThemeEnvironment {
  root: HTMLElement
  storage: Pick<Storage, 'getItem' | 'setItem'>
  media: MediaQueryList
}

const THEME_STORAGE_KEY = 'novel-vids-theme'
const validPreferences = new Set<AppThemePreference>(['system', 'light', 'dark'])

function storedPreference(storage: AppThemeEnvironment['storage']): AppThemePreference {
  const value = storage.getItem(THEME_STORAGE_KEY)
  return validPreferences.has(value as AppThemePreference) ? value as AppThemePreference : 'system'
}

export function createAppThemeController(environment: AppThemeEnvironment): AppThemeController {
  const preference = ref<AppThemePreference>(storedPreference(environment.storage))
  const systemDark = ref(environment.media.matches)
  const resolvedTheme = computed<AppTheme>(() => (
    preference.value === 'system'
      ? systemDark.value ? 'dark' : 'light'
      : preference.value
  ))

  function applyTheme() {
    environment.root.dataset.appTheme = resolvedTheme.value
    environment.root.dataset.themePreference = preference.value
    environment.root.style.colorScheme = resolvedTheme.value
  }

  function onSystemThemeChange(event: MediaQueryListEvent) {
    systemDark.value = event.matches
    applyTheme()
  }

  function setPreference(nextPreference: AppThemePreference) {
    preference.value = nextPreference
    environment.storage.setItem(THEME_STORAGE_KEY, nextPreference)
    applyTheme()
  }

  environment.media.addEventListener('change', onSystemThemeChange)
  applyTheme()

  return {
    preference,
    resolvedTheme,
    setPreference,
    destroy: () => environment.media.removeEventListener('change', onSystemThemeChange),
  }
}

function fallbackMediaQuery(): MediaQueryList {
  return {
    matches: false,
    media: '(prefers-color-scheme: dark)',
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => true,
  }
}

let appThemeController: AppThemeController | undefined

export function useAppThemeController(): AppThemeController {
  if (!appThemeController) {
    const media = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-color-scheme: dark)')
      : fallbackMediaQuery()
    const storage = typeof window !== 'undefined'
      ? window.localStorage
      : { getItem: () => null, setItem: () => undefined }
    const root = typeof document !== 'undefined' ? document.documentElement : { dataset: {}, style: {} } as HTMLElement
    appThemeController = createAppThemeController({ root, storage, media })
  }
  return appThemeController
}

export function initializeAppTheme() {
  return useAppThemeController()
}

export const appThemeControllerKey: InjectionKey<AppThemeController> = Symbol('app-theme-controller')
