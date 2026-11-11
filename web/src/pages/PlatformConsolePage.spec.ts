import {beforeEach, afterEach, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import {createPinia, setActivePinia} from 'pinia'
import {request} from '@/api'
import {useAuthStore} from '@/features/auth/authStore'
import {setLocale} from '@/i18n'
import PlatformConsolePage from './PlatformConsolePage.vue'

vi.mock('@/api', async (load) => ({...await load<typeof import('@/api')>(), request: vi.fn()}))
beforeEach(()=>{setActivePinia(createPinia());setLocale('zh');vi.resetAllMocks()})
afterEach(()=>{delete document.documentElement.dataset.appTheme})
const options = {global:{stubs:{RouterLink:{template:'<a><slot /></a>'}}}}

it.each(['dark','light'])('filters the public catalog and keeps pricing units in %s',async theme=>{
  document.documentElement.dataset.appTheme=theme
  vi.mocked(request).mockResolvedValue({data:[
    {id:'nv-1',name:'增强',kinds:['media_processing'],pricing:{tiers:[{short_side_max:1080,fps_max:30,price:5}]}},
    {id:'nv-2',name:'文本 A',kinds:['text'],pricing:{input_price_per_1m:2}},
  ]})
  const w=mount(PlatformConsolePage,{props:{section:'models'},...options})
  await flushPromises()
  expect(w.text()).toContain('¥5 / 分钟')
  await w.findAll('.filters button').find(b=>b.text()==='文本')!.trigger('click')
  expect(w.text()).toContain('nv-2')
  expect(w.text()).not.toContain('nv-1')
  w.unmount()
})

it('only reveals a new key once, clears it on team switch, and never exposes it in the key list',async()=>{
  const auth=useAuthStore();auth.activeTeamId=1
  vi.mocked(request).mockImplementation(async(_url,opt)=>opt?.method==='POST'
    ? {data:{id:9,name:'工作台',preview:'nv_a…xyz',key:'once-only-secret'}} : {data:[]})
  const w=mount(PlatformConsolePage,{props:{section:'keys'},...options})
  await flushPromises()
  expect(w.text()).toContain('当前团队下还没有')
  await w.get('input').setValue('工作台');await w.get('form').trigger('submit');await flushPromises()
  expect(w.get('.revealed code').text()).toBe('once-only-secret')
  expect(w.get('.line').text()).not.toContain('once-only-secret')
  auth.activeTeamId=2;await flushPromises()
  expect(w.text()).not.toContain('once-only-secret')
  w.unmount()
})

it('renders errors and retries the usage endpoint before showing actual totals',async()=>{
  vi.mocked(request).mockRejectedValueOnce(new Error('读取失败')).mockResolvedValue({data:{total_cost:6.2,total_records:3,daily_trend:[],by_model:[]}})
  const w=mount(PlatformConsolePage,{props:{section:'usage'},...options})
  expect(w.find('[role=status]').exists()).toBe(true)
  await flushPromises()
  expect(w.get('[role=alert]').text()).toContain('读取失败')
  await w.get('[role=alert] button').trigger('click'); await flushPromises()
  expect(w.get('.totals').text()).toContain('6.20')
  w.unmount()
})
