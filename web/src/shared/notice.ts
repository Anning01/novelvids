import { reactive } from 'vue'

export interface Notice { id: number; message: string; tone: 'info' | 'success' | 'error' }

const state = reactive<{ notices: Notice[] }>({ notices: [] })
let sequence = 0

function push(message: string, tone: Notice['tone'] = 'info') {
  const notice = { id: ++sequence, message, tone }
  state.notices.push(notice)
  window.setTimeout(() => { dismiss(notice.id) }, 3600)
}

function dismiss(id: number) {
  state.notices = state.notices.filter(item => item.id !== id)
}

export const notice = {
  state,
  info: (message: string) => push(message),
  success: (message: string) => push(message, 'success'),
  error: (message: string) => push(message, 'error'),
  dismiss,
}
