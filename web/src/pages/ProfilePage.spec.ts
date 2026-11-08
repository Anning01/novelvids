import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ProfilePage from './ProfilePage.vue'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'

function mountPage(pinia: Pinia) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/profile', component: ProfilePage },
      { path: '/projects', component: { template: '<div>Projects</div>' } },
      { path: '/members', component: { template: '<div>Members</div>' } },
      { path: '/teams', component: { template: '<div>Teams</div>' } },
      { path: '/users', component: { template: '<div>Users</div>' } },
      { path: '/settings', component: { template: '<div>Settings</div>' } },
      { path: '/billing', component: { template: '<div>Billing</div>' } },
    ],
  })
  return mount(ProfilePage, { global: { plugins: [pinia, router] } })
}

describe('ProfilePage 用户中心', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it.each(['light', 'dark'])('保存昵称并同步用户资料，失败后可以重试（%s）', async theme => {
    document.documentElement.dataset.appTheme = theme
    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    const user = { id:1, username:'qiling-profile',nickname:'微信用户',avatar_url:'',is_super_admin:false }
    auth.$patch({enabled:true,token:'t',provider:'qiling',user})
    vi.spyOn(api,'me').mockResolvedValue({data:{user,memberships:[]}} as never)
    const update = vi.spyOn(api,'updateProfile').mockRejectedValueOnce(new Error('保存失败')).mockResolvedValue({data:{...user,nickname:'新的昵称'}} as never)
    const wrapper = mountPage(pinia)
    expect(wrapper.get('[aria-label="修改昵称"]').attributes('disabled')).toBeDefined()
    await flushPromises()
    await wrapper.get('[aria-label="修改昵称"]').trigger('click')
    await wrapper.get('input[aria-label="昵称"]').setValue('  新的昵称  ')
    await wrapper.get('form.profile-nickname-form').trigger('submit')
    await flushPromises()
    expect(auth.user?.nickname).toBe('微信用户')
    expect(wrapper.find('form.profile-nickname-form').exists()).toBe(true)
    await wrapper.get('form.profile-nickname-form').trigger('submit')
    await flushPromises()
    expect(update).toHaveBeenLastCalledWith('新的昵称')
    expect(auth.user?.nickname).toBe('新的昵称')
    expect(wrapper.get('h1').text()).toBe('新的昵称')
    expect(wrapper.find('form.profile-nickname-form').exists()).toBe(false)
    wrapper.unmount()
    delete document.documentElement.dataset.appTheme
  })

  it('头像上传后同步显示，失败时保留原头像', async () => {
    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    const user = {id:1,username:'qiling-avatar',nickname:'小新',avatar_url:'/media/old.png',is_super_admin:false}
    auth.$patch({enabled:true,token:'t',provider:'qiling',user})
    vi.spyOn(api,'me').mockResolvedValue({data:{user,memberships:[]}} as never)
    const upload = vi.spyOn(api,'uploadAvatar').mockRejectedValueOnce(new Error('上传失败')).mockResolvedValue({data:{...user,avatar_url:'https://media.example/new.png'}} as never)
    const wrapper = mountPage(pinia)
    await flushPromises()
    const input = wrapper.get('input[aria-label="选择头像图片"]')
    const file = new File(['image'],'avatar.png',{type:'image/png'})
    Object.defineProperty(input.element,'files',{configurable:true,value:[file]})
    await input.trigger('change')
    await flushPromises()
    expect(auth.user?.avatar_url).toBe('/media/old.png')
    await input.trigger('change')
    await flushPromises()
    expect(upload).toHaveBeenLastCalledWith(file)
    expect(wrapper.get('.profile-avatar img').attributes('src')).toBe('https://media.example/new.png')
    wrapper.unmount()
  })

  it('上传头像的旧资料响应不会覆盖刚保存的新昵称', async () => {
    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    const user = {id:1,username:'qiling-profile',nickname:'微信用户',avatar_url:'',is_super_admin:false}
    auth.$patch({enabled:true,token:'t',user})
    vi.spyOn(api,'me').mockResolvedValue({data:{user,memberships:[]}} as never)
    vi.spyOn(api,'updateProfile').mockResolvedValue({data:{...user,nickname:'新昵称'}} as never)
    vi.spyOn(api,'uploadAvatar').mockResolvedValue({data:{...user,avatar_url:'/media/new.png'}} as never)
    const wrapper = mountPage(pinia)
    await flushPromises()
    await wrapper.get('[aria-label="修改昵称"]').trigger('click')
    await wrapper.get('input[aria-label="昵称"]').setValue('新昵称')
    await wrapper.get('form.profile-nickname-form').trigger('submit')
    await flushPromises()
    const input = wrapper.get('input[aria-label="选择头像图片"]')
    Object.defineProperty(input.element,'files',{configurable:true,value:[new File(['image'],'avatar.png',{type:'image/png'})]})
    await input.trigger('change')
    await flushPromises()
    expect(auth.user).toMatchObject({nickname:'新昵称',avatar_url:'/media/new.png'})
    wrapper.unmount()
  })

  it('展示昵称、历史花费、注册时间与团队信息', async () => {
    vi.spyOn(api, 'me').mockResolvedValue({
      data: {
        user: { id: 1, username: 'alice', nickname: '爱丽丝', avatar_url: '', is_super_admin: false, created_at: '2026-08-01 10:00:00' },
        memberships: [
          { team_id: 1, team_name: '甲队', role: 'admin', status: 1, total_cost: '12.500000', joined_at: '2026-08-02 09:00:00' },
        ],
        is_super_admin: false,
        total_cost: '12.500000',
      },
    } as never)

    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useAuthStore(pinia)
    store.$patch({
      enabled: true,
      token: 't',
      user: { id: 1, username: 'alice', nickname: '爱丽丝', avatar_url: '', is_super_admin: false },
      memberships: [],
    })

    const wrapper = mountPage(pinia)
    await flushPromises()

    expect(wrapper.text()).toContain('爱丽丝')
    expect(wrapper.text()).toContain('12.50')
    expect(wrapper.text()).toContain('注册于 2026-08-01')
    expect(wrapper.text()).toContain('甲队')
    expect(wrapper.text()).toContain('团队管理员')
    // 身份栏去掉右侧重复的「当前工作范围」
    expect(wrapper.find('.profile-context').exists()).toBe(false)
    // 只有一个团队时省掉空列表，只留一句邀请链接提示
    expect(wrapper.find('.team-list').exists()).toBe(false)
    expect(wrapper.find('.profile-teams .profile-copy').exists()).toBe(true)
  })

  it('has no password form', async () => {
    const pinia = createPinia()
    useAuthStore(pinia).$patch({ provider: 'qiling' })
    const wrapper = mountPage(pinia)
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
  })

  it('switches the team scope and shows only the actions for that membership', async () => {
    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    const user = { id: 1, username: 'qiling-generated', nickname: '安宁', avatar_url: '', is_super_admin: false }
    auth.$patch({ provider: 'qiling', qilingBound: true, legalReady: true, enabled: true, token: 't', user })
    vi.spyOn(api, 'me').mockResolvedValue({
      code: 0,
      message: '',
      data: {
        user,
        qiling_bound: true,
        is_super_admin: false,
        memberships: [
          { team_id: 1, team_name: '我的团队', role: 'admin', is_owner: true, total_cost: 0, cost_limit: 20, team_balance: 30 },
          { team_id: 2, team_name: '邀请团队', role: 'viewer', total_cost: 7, team_balance: 120 },
          { team_id: 3, team_name: '已停用的团队', role: 'creator', team_status: 0 },
        ],
      },
    })
    const wrapper = mountPage(pinia)
    await flushPromises()
    expect(wrapper.text()).not.toContain('qiling-generated')
    expect(wrapper.get('.profile-current').text()).toContain('个人团队')
    expect(wrapper.get('.profile-spend').text()).toContain('¥ 0.00')
    expect(wrapper.get('.profile-spend').text()).toContain('剩余个人额度')
    expect(wrapper.get('.profile-spend').text()).toContain('¥ 30.00')
    expect(wrapper.find('.profile-current a[href="/members"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-label="切换到 已停用的团队"]').exists()).toBe(false)
    expect(wrapper.find('.profile-footer a[href="/api/auth/legal/privacy#account-data-requests"]').exists()).toBe(true)

    // 其他团队列表中不展示当前选中的「我的团队」
    const teamListText = wrapper.get('.profile-teams .team-list').text()
    expect(teamListText).not.toContain('切换到 我的团队')
    expect(teamListText).toContain('邀请团队')
    expect(teamListText).toContain('已停用的团队')

    // 切换到邀请团队
    await wrapper.get('button[aria-label="切换到 邀请团队"]').trigger('click')
    expect(auth.activeTeamId).toBe(2)
    expect(wrapper.get('.profile-current').text()).toContain('邀请团队')
    expect(wrapper.get('.profile-spend').text()).toContain('¥ 7.00')
    expect(wrapper.get('.profile-spend').text()).not.toContain('¥ 120.00')
    expect(wrapper.find('a[href="/billing"]').exists()).toBe(false)
    expect(wrapper.find('a[href="/members"]').exists()).toBe(false)

    // 原团队「我的团队」回到其他团队列表
    expect(wrapper.get('.profile-teams .team-list').text()).toContain('我的团队')
  })

  it('shows a retryable error instead of an empty team or zero amount when loading fails', async () => {
    const pinia = createPinia()
    const user = { id: 1, username: 'alice', nickname: '爱丽丝', avatar_url: '', is_super_admin: false }
    useAuthStore(pinia).$patch({ enabled: true, token: 't', user })
    const me = vi.spyOn(api, 'me').mockRejectedValueOnce(new Error('offline')).mockResolvedValue({
      code: 0,
      message: '',
      data: { user, memberships: [], is_super_admin: false },
    })
    const wrapper = mountPage(pinia)
    expect(wrapper.get('[role="status"]').text()).toContain('正在加载个人中心')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('个人中心加载失败')
    expect(wrapper.find('.profile-grid').exists()).toBe(false)
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(me).toHaveBeenCalledTimes(2)
    expect(wrapper.get('.profile-current').text()).toContain('暂无可用团队')
  })

  it('renders platform admin mode properly when super admin has no active team', async () => {
    const pinia = createPinia()
    const store = useAuthStore(pinia)
    const user = { id: 1, username: 'admin', nickname: '系统超管', avatar_url: '', is_super_admin: true }
    store.$patch({
      enabled: true,
      token: 'token-admin',
      user,
      memberships: [],
      activeTeamId: null,
    })
    vi.spyOn(api, 'me').mockResolvedValue({
      code: 0,
      message: '',
      data: {
        user,
        memberships: [],
        is_super_admin: true,
      },
    })

    const wrapper = mountPage(pinia)
    await flushPromises()

    expect(wrapper.get('.profile-header').text()).toContain('超级管理员')
    expect(wrapper.get('.profile-current').text()).toContain('平台管理')
    expect(wrapper.find('.profile-current a[href="/teams"]').exists()).toBe(true)
    expect(wrapper.find('.profile-current a[href="/users"]').exists()).toBe(true)
    expect(wrapper.find('.profile-current a[href="/settings"]').exists()).toBe(true)
    expect(wrapper.get('.profile-spend').text()).toContain('选择团队后可查看你的消费。')
  })

  it('shows configuration link only to super admin and hides it from regular admin', async () => {
    const pinia = createPinia()
    const store = useAuthStore(pinia)
    // 普通团队管理员（is_super_admin: false）
    const user = { id: 2, username: 'admin_user', nickname: '团队管家', avatar_url: '', is_super_admin: false }
    store.$patch({
      enabled: true,
      token: 'token-admin',
      user,
      memberships: [{ team_id: 1, team_name: '创意小组', role: 'admin', status: 1, total_cost: 0 }],
      activeTeamId: 1,
    })
    vi.spyOn(api, 'me').mockResolvedValue({
      code: 0,
      message: '',
      data: {
        user,
        memberships: [{ team_id: 1, team_name: '创意小组', role: 'admin', status: 1, total_cost: 0 }],
        is_super_admin: false,
      },
    })
    const wrapper = mountPage(pinia)
    await flushPromises()

    // 普通管理员看不到模型配置入口
    expect(wrapper.find('a[href="/settings"]').exists()).toBe(false)

    // 超级管理员切换进团队，仍然可以看到配置入口
    store.$patch({
      user: { ...user, is_super_admin: true },
    })
    await flushPromises()
    expect(wrapper.find('a[href="/settings"]').exists()).toBe(true)
  })

  it('allows super admin to perform team balance top-up', async () => {
    localStorage.setItem('novelvids_active_team', '10')
    const pinia = createPinia()
    const store = useAuthStore(pinia)
    const user = { id: 1, username: 'boss', nickname: '系统超管', avatar_url: '', is_super_admin: true }
    store.$patch({
      enabled: true,
      token: 'token-boss',
      user,
      memberships: [{ team_id: 10, team_name: '制作一组', role: 'admin', status: 1, total_cost: 0, team_balance: 100 }],
      activeTeamId: 10,
    })
    const meSpy = vi.spyOn(api, 'me').mockResolvedValue({
      code: 0,
      message: '',
      data: {
        user,
        memberships: [{ team_id: 10, team_name: '制作一组', role: 'admin', status: 1, total_cost: 0, team_balance: 100 }],
        is_super_admin: true,
      },
    })
    const topUpSpy = vi.spyOn(api, 'teamTopUp').mockResolvedValue({
      code: 0,
      message: '',
      data: { team_id: 10, balance: 300 },
    })

    const wrapper = mountPage(pinia)
    await flushPromises()

    // 点击充值按钮打开弹窗
    const topUpBtn = wrapper.find('.profile-topup-btn')
    expect(topUpBtn.exists()).toBe(true)
    await topUpBtn.trigger('click')

    expect(wrapper.find('.profile-modal-card').exists()).toBe(true)
    expect(wrapper.get('.profile-modal-title').text()).toContain('团队充值')
    expect(wrapper.get('.profile-topup-team-name').text()).toContain('制作一组')

    // 输入充值金额并提交
    const amountInput = wrapper.get('.profile-topup-field input[type="number"]')
    await amountInput.setValue(200)

    await wrapper.get('form.profile-topup-form').trigger('submit.prevent')
    await flushPromises()

    expect(topUpSpy).toHaveBeenCalledWith({
      team_id: 10,
      amount: 200,
      note: '管理端充值',
    })
    expect(meSpy).toHaveBeenCalled()
    expect(wrapper.find('.profile-modal-card').exists()).toBe(false)
  })

  it('allows non-super admin to initiate wechat pay recharge order on top up modal', async () => {
    localStorage.setItem('novelvids_active_team', '10')
    const pinia = createPinia()
    const store = useAuthStore(pinia)
    const user = { id: 2, username: 'editor', nickname: '创作者管理', avatar_url: '', is_super_admin: false }
    store.$patch({
      enabled: true,
      token: 'token-editor',
      user,
      memberships: [{ team_id: 10, team_name: '短剧二组', role: 'admin', status: 1, total_cost: 0, team_balance: 50 }],
      activeTeamId: 10,
    })
    vi.spyOn(api, 'me').mockResolvedValue({
      code: 0,
      message: '',
      data: {
        user,
        memberships: [{ team_id: 10, team_name: '短剧二组', role: 'admin', status: 1, total_cost: 0, team_balance: 50 }],
        is_super_admin: false,
      },
    })
    const rechargeSpy = vi.spyOn(api, 'createRechargeOrder').mockResolvedValue({
      code: 0,
      message: '',
      data: {
        id: 1,
        out_trade_no: 'REC_TEST_123',
        team_id: 10,
        amount: 100,
        status: 'pending',
        payment_method: 'wechat_native',
        code_url: 'weixin://wxpay/bizpayurl?pr=mock_123',
        created_at: new Date().toISOString(),
      },
    })

    const wrapper = mountPage(pinia)
    await flushPromises()

    const topUpBtn = wrapper.find('.profile-topup-btn')
    expect(topUpBtn.exists()).toBe(true)
    await topUpBtn.trigger('click')

    expect(wrapper.find('.profile-modal-card').exists()).toBe(true)
    expect(wrapper.find('form.profile-topup-form').exists()).toBe(true)

    // 输入充值金额并提交微信支付
    const amountInput = wrapper.get('.profile-topup-field input[type="number"]')
    await amountInput.setValue(100)
    await wrapper.get('form.profile-topup-form').trigger('submit.prevent')
    await flushPromises()

    expect(rechargeSpy).toHaveBeenCalledWith({
      team_id: 10,
      amount: 100,
      note: '微信支付充值',
    })
    expect(wrapper.find('.profile-qrcode-box').exists()).toBe(true)
    expect(wrapper.get('.profile-qrcode-order-no').text()).toContain('REC_TEST_123')
  })

  it('supports password change and logout in password mode', async () => {
    const pinia = createPinia()
    const store = useAuthStore(pinia)
    const user = { id: 1, username: 'bob', nickname: '鲍勃', avatar_url: '', is_super_admin: false }
    store.$patch({
      enabled: true,
      token: 'token-bob',
      provider: 'password',
      user,
      memberships: [{ team_id: 1, team_name: '测试队', role: 'admin', status: 1, total_cost: 0 }],
      activeTeamId: 1,
    })
    vi.spyOn(api, 'me').mockResolvedValue({
      code: 0,
      message: '',
      data: {
        user,
        memberships: [{ team_id: 1, team_name: '测试队', role: 'admin', status: 1, total_cost: 0 }],
        is_super_admin: false,
      },
    })
    const changePasswordSpy = vi.spyOn(api, 'changePassword').mockResolvedValue({ code: 0, message: 'ok', data: null } as never)
    const logoutSpy = vi.spyOn(api, 'logout').mockResolvedValue({ code: 0, message: 'ok', data: null } as never)

    const wrapper = mountPage(pinia)
    await flushPromises()

    // 检查改密表单存在
    expect(wrapper.find('details.profile-password').exists()).toBe(true)
    const inputs = wrapper.findAll('input[type="password"]')
    expect(inputs.length).toBe(3)
    await inputs[0].setValue('oldpass123')
    await inputs[1].setValue('newpass1234')
    await inputs[2].setValue('newpass1234')

    await wrapper.find('form.password-form').trigger('submit.prevent')
    await flushPromises()
    expect(changePasswordSpy).toHaveBeenCalledWith('oldpass123', 'newpass1234')

    // 检查退出登录
    const logoutBtn = wrapper.find('.profile-logout')
    expect(logoutBtn.exists()).toBe(true)
    await logoutBtn.trigger('click')
    await flushPromises()
    expect(logoutSpy).toHaveBeenCalled()
  })
})
