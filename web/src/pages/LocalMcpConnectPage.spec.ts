import {flushPromises, mount} from '@vue/test-utils'
import {createPinia, setActivePinia} from 'pinia'
import {afterEach, beforeEach, expect, it, vi} from 'vitest'
import LocalMcpConnectPage from './LocalMcpConnectPage.vue'
import {useAuthStore} from '@/features/auth/authStore'
import {request} from '@/api'

vi.mock('vue-router', () => ({useRoute: () => ({params:{code:'example'}})}))
vi.mock('@/api', async original => ({
  ...await original<typeof import('@/api')>(), request: vi.fn(),
  authHeaders: () => ({Authorization:'Bearer test-only'}),
}))

beforeEach(() => {setActivePinia(createPinia());vi.clearAllMocks()})
afterEach(() => {localStorage.clear()})

it.each(['light','dark'])('uses the selected team and existing browser session only after confirming (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const auth = useAuthStore()
  auth.$patch({activeTeamId:3,memberships:[
    {team_id:3,team_name:'甲',role:'creator'}, {team_id:4,team_name:'乙',role:'admin'},
  ]})
  vi.mocked(request).mockResolvedValue({})
  const view = mount(LocalMcpConnectPage)
  try {
    expect(view.get('select').element.value).toBe('3')
    await view.get('select').setValue('4')
    expect(request).not.toHaveBeenCalled()
    await view.get('button').trigger('click')
    await flushPromises()
    expect(request).toHaveBeenCalledWith('/auth/local-mcp/example/approve',{method:'POST', headers:{Authorization:'Bearer test-only','X-Team-Id':'4'}})
    expect(view.find('[role=status]').exists()).toBe(true)
    expect(auth.activeTeamId).toBe(4)
  } finally {view.unmount();delete document.documentElement.dataset.appTheme}
})
