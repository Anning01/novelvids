
import { tr } from '@/i18n'
import { reactive } from 'vue'

export type AppConfirmTone = 'neutral' | 'warning' | 'danger'

export interface AppConfirmOptions {
  title: string
  message?: string
  details?: string[]
  confirmLabel?: string
  cancelLabel?: string
  tone?: AppConfirmTone
}

export const appConfirmState = reactive({
  open: false,
  title: '',
  message: '',
  details: [] as string[],
  confirmLabel: tr('确认'),
  cancelLabel: tr('取消'),
  tone: 'danger' as AppConfirmTone,
})

let pendingResolve: ((confirmed: boolean) => void) | undefined

export function resolveAppConfirm(confirmed: boolean) {
  if (!appConfirmState.open) return
  appConfirmState.open = false
  const resolve = pendingResolve
  pendingResolve = undefined
  resolve?.(confirmed)
}

export function appConfirm(options: AppConfirmOptions) {
  if (appConfirmState.open) resolveAppConfirm(false)
  Object.assign(appConfirmState, {
    open: true,
    title: options.title,
    message: options.message || '',
    details: options.details || [],
    confirmLabel: options.confirmLabel || tr('确认'),
    cancelLabel: options.cancelLabel || tr('取消'),
    tone: options.tone || 'danger',
  })
  return new Promise<boolean>(resolve => {
    pendingResolve = resolve
  })
}
