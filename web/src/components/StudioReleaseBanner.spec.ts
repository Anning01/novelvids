import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { useAuthStore } from '@/features/auth/authStore'
import { setLocale } from '@/i18n'
import StudioReleaseBanner from './StudioReleaseBanner.vue'

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); localStorage.clear() })
async function render(admin: boolean, build = 'old', required: string[] = []) {
  vi.stubEnv('VITE_STUDIO_BUILD', 'old')
  vi.stubGlobal('fetch', vi.fn(async(url: string) => ({json: async () => url.includes('studio-build') ? {build} :
    {data: {installed:'1.1.0', latest:{version:'1.2.0', required, online:true, summary:'支持新模型'}, updater:{phase:'idle'}}}})))
  const pinia = createPinia()
  useAuthStore(pinia).$patch({user:{is_super_admin:admin}})
  setLocale('zh')
  const wrapper = mount(StudioReleaseBanner, {global:{plugins:[pinia]}})
  await flushPromises()
  return wrapper
}
it.each([true,false])('distinguishes deployment owner and member, admin=%s', async admin => {
  const w = await render(admin, 'old', ['pixel_tier_images'])
  expect(w.text().includes('升级工作台') && w.find('button').exists()).toBe(admin)
  expect(w.text().includes('请联系部署管理员')).toBe(!admin)
  expect(w.text()).not.toContain('刷新页面')
  w.unmount()
})
it('only offers a manual refresh after frontend replacement and honors a draft guard', async () => {
  const guard = vi.fn((e: Event) => e.preventDefault())
  window.addEventListener('studio-before-refresh', guard)
  const w = await render(false,'new')
  expect(guard).not.toHaveBeenCalled()
  await w.get('button').trigger('click')
  expect(w.text()).toContain('分镜修改尚未保存')
  window.removeEventListener('studio-before-refresh', guard)
  w.unmount()
})
it('remembers dismissal only for this optional release', async () => {
  const w = await render(false)
  await w.get('button').trigger('click')
  expect(w.find('[role="region"]').exists()).toBe(false)
  expect(localStorage.getItem('studio-release-dismissed')).toBe('1.2.0')
  w.unmount()
})
