import { reactive } from 'vue'

export interface Notice { id: number; message: string; tone: 'info' | 'success' | 'error' }
const state = reactive<{ notices: Notice[] }>({ notices: [] })
let sequence = 0
function push(message: string, tone: Notice['tone'] = 'info') {
  const notice = { id: ++sequence, message, tone }
  state.notices.push(notice)
  window.setTimeout(() => { state.notices = state.notices.filter(item => item.id !== notice.id) }, 3200)
}
export const notice = { state, info: (message: string) => push(message), success: (message: string) => push(message, 'success'), error: (message: string) => push(message, 'error') }
