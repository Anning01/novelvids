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
  await w.findAll('.filters button').find(b=>b.text().startsWith('文本'))!.trigger('click')
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

it.each(['dark', 'light'])('uses one period for the chart, total, and model costs in %s', async theme => {
  document.documentElement.dataset.appTheme = theme
  vi.mocked(request).mockResolvedValueOnce({data: {
    total_cost: 0, total_records: 0, daily_trend: [{date:'2026-11-06',cost:0}], by_model: [],
  }}).mockResolvedValueOnce({data: {
    total_cost: 3, total_records: 2, daily_trend: [{date:'2026-10-14',cost:3}],
    by_model: [{model:'模型 A',cost:3,record_count:2}],
  }})
  const w = mount(PlatformConsolePage, {props:{section:'usage'}, ...options})
  await flushPromises()
  expect(request).toHaveBeenNthCalledWith(1, '/platform/usage?days=7')
  expect(w.text()).toContain('暂无计费记录')
  const period = w.get('[aria-label="用量时间范围"]')
  const month = period.get('button[aria-pressed="false"]')
  await month.trigger('focus')
  await month.trigger('click')
  await flushPromises()

  expect(request).toHaveBeenNthCalledWith(2, '/platform/usage?days=30')
  expect(month.attributes('aria-pressed')).toBe('true')
  expect(w.get('.totals').text()).toContain('¥ 3.00')
  expect(w.get('.chart [tabindex="0"]').attributes('aria-label')).toContain('2026-10-14')
  expect(w.get('.line').text()).toContain('模型 A 2 次计费')
  expect(w.get('.line').text()).toContain('¥ 3.00')
  w.unmount()
})

it('toggles usage trend metric and searches model statistics in the table', async () => {
  vi.mocked(request).mockResolvedValue({
    data: {
      total_cost: 10.5,
      total_records: 25,
      daily_trend: [{ date: '2026-11-10', cost: 4.5 }, { date: '2026-11-11', cost: 6.0 }],
      by_model: [
        { model: 'doubao-seedance-2-0-fast', cost: 6.0, record_count: 15 },
        { model: 'doubao-seedream-5-0-flash', cost: 4.5, record_count: 10 },
      ],
    },
  })
  const w = mount(PlatformConsolePage, { props: { section: 'usage' }, ...options })
  await flushPromises()

  // Verify metric cards
  expect(w.get('.totals').text()).toContain('10.50')
  expect(w.get('.totals').text()).toContain('25')

  // Verify donut distribution chart
  expect(w.get('.donut-center-cost').text()).toContain('10.50')
  expect(w.text()).toContain('视频模型')
  expect(w.text()).toContain('图片模型')

  // Toggle chart metric to 调用次数
  const callsToggle = w.findAll('.segmented-btn').find(b => b.text().includes('调用次数'))
  expect(callsToggle).toBeDefined()
  await callsToggle!.trigger('click')
  await flushPromises()
  expect(callsToggle!.classes()).toContain('is-active')

  // Search model table
  const searchInput = w.get('.table-search-pill input')
  await searchInput.setValue('seedream')
  await flushPromises()
  expect(w.text()).toContain('doubao-seedream-5-0-flash')
  expect(w.text()).not.toContain('doubao-seedance-2-0-fast')

  w.unmount()
})

it('renders guided empty state and interacts with create drawer', async () => {
  const auth = useAuthStore()
  auth.activeTeamId = 1
  vi.mocked(request).mockResolvedValue({ data: [] })

  const w = mount(PlatformConsolePage, { props: { section: 'keys' }, ...options })
  await flushPromises()

  // Verify empty state (Image 2)
  expect(w.find('.keys-empty-card').exists()).toBe(true)
  expect(w.get('.empty-title').text()).toBe('还没有 API Key')
  expect(w.text()).toContain('创建你的第一个 API Key')
  expect(w.get('.empty-tag-pill').text()).toContain('支持图片 · 视频 · 文本模型')

  // Open drawer via button
  const drawer = w.get('.drawer-panel')
  expect(drawer.classes()).not.toContain('is-open')
  await w.get('.btn-create-key-pill').trigger('click')
  expect(drawer.classes()).toContain('is-open')

  // Verify drawer elements (Image 3)
  expect(drawer.text()).toContain('创建 API Key')
  expect(drawer.text()).toContain('密钥名称')
  expect(drawer.text()).toContain('可用模型')
  expect(drawer.text()).toContain('视频模型')
  expect(drawer.text()).toContain('图片模型')
  expect(drawer.text()).toContain('文本模型')
  expect(drawer.text()).toContain('授权有效期')
  expect(drawer.text()).toContain('永久')
  expect(drawer.text()).toContain('自定义')

  // Expand video models and verify specific models
  const expandBtns = drawer.findAll('.btn-expand-kind')
  expect(expandBtns.length).toBe(3)
  await expandBtns[0]!.trigger('click')
  expect(drawer.text()).toContain('选择具体模型')
  expect(drawer.text()).toContain('doubao-seedance-2-0-fast')

  // Select custom validity mode and verify presets + date picker + preview
  const radios = drawer.findAll('.validity-native-radio')
  expect(radios.length).toBe(2)
  await radios[1]!.setValue(true)
  expect(drawer.text()).toContain('选择到期时间')
  expect(drawer.text()).toContain('7天后')
  expect(drawer.text()).toContain('30天后')
  expect(drawer.find('.custom-date-input').exists()).toBe(true)
  expect(drawer.find('.expire-preview-callout').text()).toContain('过期失效')

  // Click 7 days preset
  const presetBtns = drawer.findAll('.preset-pill-btn')
  expect(presetBtns.length).toBe(4)
  await presetBtns[0]!.trigger('click')
  expect(presetBtns[0]!.classes()).toContain('is-active')

  // Close drawer via cancel button
  await w.get('.btn-drawer-cancel').trigger('click')
  expect(drawer.classes()).not.toContain('is-open')

  w.unmount()
})

it('renders keys table with header stats, toolbar filters and row actions', async () => {
  const auth = useAuthStore()
  auth.activeTeamId = 1
  vi.mocked(request).mockImplementation(async (url) => {
    if (url.includes('/platform/usage')) {
      return { data: { total_cost: 8.1296, total_records: 1892, daily_trend: [], by_model: [] } }
    }
    return {
      data: [
        { id: 1, name: '我的本地猫影', preview: 'sk-3a9f12345678', created_at: '2026-11-10T14:20:00Z', purpose: 'studio' },
        { id: 2, name: '前端测试', preview: 'sk-8f2d87654321', created_at: '2026-11-09T18:36:00Z', purpose: 'api' },
      ],
    }
  })

  const w = mount(PlatformConsolePage, { props: { section: 'keys' }, ...options })
  await flushPromises()

  // Header stats (Image 1)
  expect(w.get('.keys-header-stats').text()).toContain('2')
  expect(w.get('.keys-header-stats').text()).toContain('1,892 次')
  expect(w.get('.keys-header-stats').text()).toContain('8.1296')

  // Table rows and content
  expect(w.find('.keys-table').exists()).toBe(true)
  expect(w.text()).toContain('我的本地猫影')
  expect(w.text()).toContain('本地猫影')
  expect(w.text()).toContain('前端测试')
  expect(w.text()).toContain('通用 API')
  expect(w.text()).toContain('启用')

  // Search filter
  const searchInput = w.get('.keys-search-pill input')
  await searchInput.setValue('前端测试')
  await flushPromises()
  expect(w.text()).toContain('前端测试')
  expect(w.text()).not.toContain('我的本地猫影')

  w.unmount()
})

it('renders loading skeleton and animations on refresh and data load', async () => {
  let resolveReq: ((val: unknown) => void) | null = null
  vi.mocked(request).mockImplementation(() => new Promise((resolve) => {
    resolveReq = resolve
  }))

  const w = mount(PlatformConsolePage, { props: { section: 'usage' }, ...options })

  // 1. Loading stage with skeleton charts & equalizer icon
  expect(w.find('[role=status]').exists()).toBe(true)
  expect(w.find('.loading-badge').text()).toContain('加载中')
  expect(w.find('.skeleton-chart-bars').exists()).toBe(true)
  expect(w.find('.skeleton-donut-ring').exists()).toBe(true)
  expect(w.find('.usage-brand-icon').classes()).toContain('is-loading')

  // Resolve request
  resolveReq!({
    data: {
      total_cost: 8.12964,
      total_records: 50,
      daily_trend: [{ date: '2026-11-06', cost: 1.5 }, { date: '2026-11-08', cost: 4.0 }],
      by_model: [{ model: 'doubao-seedance-2-1-turbo', cost: 4.0, record_count: 20 }],
    },
  })
  await flushPromises()

  // 2. Data loaded: animations & charts mounted
  expect(w.find('.loading-stage').exists()).toBe(false)
  expect(w.find('.usage-brand-icon').classes()).not.toContain('is-loading')
  expect(w.find('.brand-chart-icon-svg').exists()).toBe(true)
  expect(w.findAll('.chart-bar-wrap').length).toBe(2)
  expect(w.find('.donut-svg').exists()).toBe(true)

  // 3. Click refresh button triggers reload
  const refreshBtn = w.find('.period-refresh-btn')
  expect(refreshBtn.exists()).toBe(true)
  await refreshBtn.trigger('click')
  expect(request).toHaveBeenCalledTimes(2)

  w.unmount()
})
