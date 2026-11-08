<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ArrowRight,
  Building2,
  CheckCircle2,
  ChevronRight,
  CreditCard,
  FileText,
  FolderOpen,
  LoaderCircle,
  Camera,
  Pencil,
  LogOut,
  QrCode,
  Settings,
  ShieldCheck,
  UserRound,
  UsersRound,
  Wallet,
  X,
} from 'lucide-vue-next'
import { API_BASE, api, mediaUrl } from '@/api'
import AppButton from '@/components/AppButton.vue'
import QilingLogin from '@/features/auth/QilingLogin.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { tr } from '@/i18n'
import { notice } from '@/shared/notice'
import type { Membership, RechargeOrder, TeamRole } from '@/types'

const auth = useAuthStore()
const passwordForm = ref({ oldPassword: '', newPassword: '', confirmPassword: '' })
const changing = ref(false)
const signingOut = ref(false)
const loading = ref(true)
const loadError = ref(false)
const avatarFailed = ref(false)
const avatarInput = ref<HTMLInputElement | null>(null)
const uploadingAvatar = ref(false)
const editingNickname = ref(false)
const nicknameDraft = ref('')
const nicknameInput = ref<HTMLInputElement | null>(null)
const savingNickname = ref(false)

async function editNickname() {
  nicknameDraft.value = auth.user?.nickname || ''
  editingNickname.value = true
  await nextTick()
  nicknameInput.value?.focus()
  nicknameInput.value?.select()
}

async function saveNickname() {
  const nickname = nicknameDraft.value.trim()
  if (!nickname || savingNickname.value) return
  savingNickname.value = true
  try {
    auth.user = (await api.updateProfile(nickname)).data
    editingNickname.value = false
    notice.success(tr('昵称已更新'))
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('昵称保存失败'))
  } finally {
    savingNickname.value = false
  }
}

async function changeAvatar(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || uploadingAvatar.value) return
  uploadingAvatar.value = true
  try {
    auth.user = (await api.uploadAvatar(file)).data
    notice.success(tr('头像已更新'))
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('头像上传失败'))
  } finally {
    uploadingAvatar.value = false
  }
}

// 充值弹窗状态
const showTopUpModal = ref(false)
const topUpStep = ref<'form' | 'qrcode' | 'success'>('form')
const topUpMode = ref<'wechat' | 'direct'>('wechat')
const topUpAmount = ref<number | ''>(50)
const topUpNote = ref('')
const topUpSubmitting = ref(false)
const currentOrder = ref<RechargeOrder | null>(null)
const qrCodeDataUrl = ref('')
const qrCodeLoading = ref(false)
const topUpPaidDetail = ref<{ amount: number; balance: number } | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

const showUsername = computed(() => auth.provider === 'password' && !auth.user?.username.startsWith('qiling-'))
const displayName = computed(() => auth.user?.nickname || (showUsername.value ? auth.user?.username : '') || tr('我的账号'))
const avatarText = computed(() => Array.from(displayName.value.trim())[0]?.toUpperCase() || '?')
const avatarUrl = computed(() => mediaUrl(auth.user?.avatar_url))
watch(avatarUrl, () => { avatarFailed.value = false })

const current = computed(() => auth.membership)
const isPlatform = computed(() => auth.role === 'super')

// 其他团队：只列当前团队之外的团队
const otherTeams = computed(() =>
  auth.memberships
    .filter(team => team.team_id !== auth.activeTeamId)
    .sort((a, b) => Number(Boolean(b.is_owner)) - Number(Boolean(a.is_owner)))
)

const limit = computed(() => current.value?.cost_limit)
const remaining = computed(() => {
  const used = current.value?.total_cost
  if (limit.value == null || used == null) return null
  const amount = Number(limit.value) - Number(used)
  return Number.isFinite(amount) ? Math.max(0, amount) : null
})

function roleLabel(role: TeamRole) {
  return tr({ admin: '团队管理员', creator: '创作者', viewer: '查看者' }[role])
}

function unavailable(team: Membership) {
  if (team.team_status === 0) return tr('团队已停用')
  if (team.status === 0) return tr('成员资格已禁用')
  return ''
}

function money(value: number | string | null | undefined) {
  if (value == null || value === '' || !Number.isFinite(Number(value))) return '—'
  return '¥ ' + Number(value).toFixed(2)
}

function selectTeam(team: Membership) {
  if (unavailable(team) || team.team_id === auth.activeTeamId) return
  auth.setActiveTeam(team.team_id)
}

function openTopUpModal() {
  topUpStep.value = 'form'
  topUpMode.value = auth.isSuperAdmin ? 'direct' : 'wechat'
  topUpAmount.value = ''
  topUpNote.value = ''
  currentOrder.value = null
  qrCodeDataUrl.value = ''
  topUpPaidDetail.value = null
  stopPolling()
  showTopUpModal.value = true
}

function closeTopUpModal() {
  stopPolling()
  showTopUpModal.value = false
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onUnmounted(() => {
  stopPolling()
})

async function generateQrCode(url: string) {
  qrCodeLoading.value = true
  try {
    const QRCode = (await import('qrcode')).default
    qrCodeDataUrl.value = await QRCode.toDataURL(url, {
      width: 220,
      margin: 1,
      color: { dark: '#000000', light: '#ffffff' },
    })
  } catch (err) {
    console.error('QR code generation error', err)
  } finally {
    qrCodeLoading.value = false
  }
}

function startPolling(outTradeNo: string) {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      const res = await api.queryRechargeOrder(outTradeNo)
      if (res.data.status === 'paid') {
        stopPolling()
        topUpPaidDetail.value = {
          amount: Number(res.data.amount),
          balance: Number(res.data.balance_after ?? current.value?.team_balance ?? 0),
        }
        topUpStep.value = 'success'
        notice.success(tr('充值成功！余额已到账'))
        await auth.refreshMe()
      }
    } catch {
      // ignore transient polling errors
    }
  }, 2000)
}

function selectPresetAmount(val: number) {
  topUpAmount.value = val
}

async function handleTopUpSubmit() {
  if (!current.value || topUpSubmitting.value) return
  const amount = Number(topUpAmount.value)
  if (!amount || Number.isNaN(amount) || amount <= 0) {
    notice.error(tr('请输入有效的充值金额'))
    return
  }
  topUpSubmitting.value = true
  try {
    if (topUpMode.value === 'direct' && auth.isSuperAdmin) {
      await api.teamTopUp({
        team_id: current.value.team_id,
        amount,
        note: topUpNote.value.trim() || tr('管理端充值'),
      })
      notice.success(tr('充值成功'))
      closeTopUpModal()
      await auth.refreshMe()
      return
    }

    const res = await api.createRechargeOrder({
      team_id: current.value.team_id,
      amount,
      note: topUpNote.value.trim() || tr('微信支付充值'),
    })
    const order = res.data
    currentOrder.value = order
    topUpStep.value = 'qrcode'
    if (order.code_url) {
      await generateQrCode(order.code_url)
    }
    startPolling(order.out_trade_no)
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('发起充值失败'))
  } finally {
    topUpSubmitting.value = false
  }
}

async function triggerMockPay() {
  if (!currentOrder.value) return
  topUpSubmitting.value = true
  try {
    const res = await api.mockPayRechargeOrder(currentOrder.value.out_trade_no)
    stopPolling()
    topUpPaidDetail.value = {
      amount: Number(res.data.amount),
      balance: Number(res.data.balance_after ?? current.value?.team_balance ?? 0),
    }
    topUpStep.value = 'success'
    notice.success(tr('模拟支付成功！余额已到账'))
    await auth.refreshMe()
  } catch (err) {
    notice.error(err instanceof Error ? err.message : tr('模拟支付失败'))
  } finally {
    topUpSubmitting.value = false
  }
}

async function load() {
  loading.value = true
  loadError.value = false
  try {
    await auth.refreshMe()
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

async function changePassword() {
  const { oldPassword, newPassword, confirmPassword } = passwordForm.value
  if (changing.value || !oldPassword || newPassword.length < 8) return
  if (newPassword !== confirmPassword) {
    notice.error(tr('两次输入的新密码不一致'))
    return
  }
  changing.value = true
  try {
    await api.changePassword(oldPassword, newPassword)
    notice.success(tr('密码已修改'))
    passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('修改密码失败'))
  } finally {
    changing.value = false
  }
}

async function logout() {
  if (signingOut.value) return
  signingOut.value = true
  try {
    await auth.logout()
  } finally {
    signingOut.value = false
  }
}

async function qilingBound() {
  await load()
  if (!loadError.value) notice.success(tr('器灵账号已绑定'))
}

onMounted(load)
</script>

<template>
  <main class="profile-page">
    <!-- 身份栏：头像、昵称、账号状态和注册日期左对齐，去掉右侧重复的「当前工作范围」。器灵账号继续隐藏系统生成的用户名 -->
    <header class="profile-header">
      <div class="profile-avatar-editor">
        <div class="profile-avatar" aria-hidden="true">
          <img v-if="avatarUrl && !avatarFailed" :src="avatarUrl" alt="" @error="avatarFailed = true" />
          <span v-else>{{ avatarText }}</span>
        </div>
        <button v-if="auth.user" type="button" class="profile-avatar-change" :disabled="loading || loadError || uploadingAvatar" :aria-label="tr('更换头像')" :title="tr('更换头像：JPG、PNG、WebP，最大 5MB')" @click="avatarInput?.click()">
          <LoaderCircle v-if="uploadingAvatar" :size="13" class="is-spinning" /><Camera v-else :size="13" />
        </button>
        <input ref="avatarInput" class="profile-avatar-input" type="file" accept="image/jpeg,image/png,image/webp" :aria-label="tr('选择头像图片')" :disabled="uploadingAvatar" @change="changeAvatar" />
      </div>
      <div class="profile-identity">
        <p class="profile-caption">{{ tr('个人中心') }}</p>
        <div class="profile-name-line">
          <h1>{{ displayName }}</h1>
          <span v-if="auth.isSuperAdmin" class="profile-badge">{{ tr('超级管理员') }}</span>
          <AppButton v-if="auth.user && !editingNickname" type="button" variant="ghost" size="sm" icon-only :aria-label="tr('修改昵称')" :disabled="loading || loadError" @click="editNickname"><Pencil :size="14" /></AppButton>
        </div>
        <form v-if="editingNickname" class="profile-nickname-form" @submit.prevent="saveNickname">
          <input ref="nicknameInput" v-model="nicknameDraft" :aria-label="tr('昵称')" autocomplete="nickname" maxlength="100" required :disabled="savingNickname" />
          <AppButton type="submit" size="sm" :disabled="!nicknameDraft.trim() || savingNickname" :loading="savingNickname">{{ tr('保存') }}</AppButton>
          <AppButton type="button" variant="ghost" size="sm" :disabled="savingNickname" @click="editingNickname = false">{{ tr('取消') }}</AppButton>
        </form>
        <div class="profile-meta">
          <span v-if="showUsername && auth.user?.username">@{{ auth.user.username }}</span>
          <span v-if="auth.provider === 'qiling'">{{ auth.qilingBound ? tr('器灵账号已绑定') : tr('器灵账号待绑定') }}</span>
          <span v-if="auth.user?.created_at">{{ tr('注册于 {p0}', { p0: auth.user.created_at.slice(0, 10) }) }}</span>
        </div>
      </div>
    </header>

    <div v-if="loading" class="profile-card profile-state" role="status">{{ tr('正在加载个人中心…') }}</div>
    <div v-else-if="loadError" class="profile-card profile-state" role="alert">
      <span>{{ tr('个人中心加载失败，请重试。') }}</span>
      <AppButton type="button" variant="secondary" @click="load">{{ tr('重试') }}</AppButton>
    </div>

    <div v-else class="profile-grid">
      <!-- 团队与消费：合成一块全宽区域。顶部显示当前团队名称、角色和「个人团队」标记，下方放「进入项目」及有权限时的「成员管理」。用一条细分隔线把消费放在同一区域，金额按行展示，不再为 ¥0.00 单独撑开一张大卡。本人消费、团队余额和个人限额仍明确分开。 -->
      <section class="profile-card profile-combined-card" aria-labelledby="profile-current-title">
        <div class="profile-current">
          <div class="profile-section-header">
            <h2 id="profile-current-title">
              <Building2 :size="18" aria-hidden="true" />
              {{ tr('当前团队') }}
            </h2>
          </div>

          <template v-if="current">
            <div class="profile-team-summary">
              <div class="profile-team-identity">
                <span class="profile-team-name">{{ current.team_name }}</span>
                <div class="profile-badges">
                  <span v-if="current.is_owner" class="profile-badge">{{ tr('个人团队') }}</span>
                  <span class="profile-badge is-neutral">{{ roleLabel(current.role) }}</span>
                </div>
              </div>
              <div class="profile-actions">
                <RouterLink class="profile-link is-primary" to="/projects">
                  <FolderOpen :size="15" aria-hidden="true" />
                  {{ tr('进入项目') }}
                  <ArrowRight :size="14" aria-hidden="true" />
                </RouterLink>
                <RouterLink v-if="current.role === 'admin'" class="profile-link" to="/members">
                  <UsersRound :size="15" aria-hidden="true" />
                  {{ tr('成员管理') }}
                </RouterLink>
                <!-- 配置仅超级管理员可见 -->
                <RouterLink v-if="auth.canAccessSettings" class="profile-link" to="/settings">
                  <Settings :size="15" aria-hidden="true" />
                  {{ tr('模型配置') }}
                </RouterLink>
                <!-- 充值操作：管理员、创作者或超级管理员可调出充值对话框 -->
                <AppButton
                  v-if="current.role === 'admin' || current.role === 'creator' || auth.isSuperAdmin"
                  class="profile-link profile-topup-btn"
                  variant="secondary"
                  size="sm"
                  type="button"
                  @click="openTopUpModal"
                >
                  <CreditCard :size="15" aria-hidden="true" />
                  {{ tr('充值') }}
                </AppButton>
              </div>
            </div>
          </template>
          <template v-else-if="isPlatform">
            <div class="profile-team-summary">
              <div class="profile-team-identity">
                <span class="profile-team-name">{{ tr('平台管理') }}</span>
              </div>
              <div class="profile-actions">
                <!-- 配置仅超级管理员可见 -->
                <RouterLink class="profile-link" to="/settings">
                  <Settings :size="15" aria-hidden="true" />
                  {{ tr('系统配置') }}
                </RouterLink>
                <RouterLink class="profile-link" to="/teams">
                  <Building2 :size="15" aria-hidden="true" />
                  {{ tr('团队管理') }}
                  <ChevronRight :size="15" aria-hidden="true" />
                </RouterLink>
                <RouterLink class="profile-link" to="/users">
                  <UserRound :size="15" aria-hidden="true" />
                  {{ tr('用户管理') }}
                </RouterLink>
              </div>
            </div>
            <p class="profile-copy">{{ tr('从下方切换到团队，可查看对应的项目与消费。') }}</p>
          </template>
          <p v-else class="profile-copy">{{ tr('暂无可用团队，可通过他人的邀请链接加入。') }}</p>
        </div>

        <div class="profile-divider" role="separator" />

        <div class="profile-spend" aria-labelledby="profile-spend-title">
          <div class="profile-spend-header">
            <h3 id="profile-spend-title" class="profile-subheading">
              <Wallet :size="16" aria-hidden="true" />
              {{ tr('消费概览') }}
            </h3>
            <RouterLink v-if="current && auth.canAccessBilling" class="profile-text-link" to="/billing">
              {{ current.role === 'admin' ? tr('查看团队成本') : tr('查看我的成本') }}
              <ChevronRight :size="14" aria-hidden="true" />
            </RouterLink>
          </div>

          <template v-if="current">
            <dl class="profile-amounts-line">
              <div class="profile-amount-item is-cost">
                <dt>{{ tr('当前团队 · 本人累计消费') }}</dt>
                <dd>{{ money(current.total_cost) }}</dd>
              </div>
              <div v-if="current.role === 'admin' && current.team_balance != null" class="profile-amount-item">
                <dt>{{ tr('团队余额') }}</dt>
                <dd class="profile-balance-cell">
                  <span>{{ money(current.team_balance) }}</span>
                  <AppButton
                    variant="secondary"
                    size="xs"
                    type="button"
                    class="profile-topup-btn"
                    :aria-label="tr('为团队充值')"
                    @click="openTopUpModal"
                  >
                    <CreditCard :size="12" aria-hidden="true" />
                    {{ tr('充值') }}
                  </AppButton>
                </dd>
              </div>
              <div v-if="limit != null" class="profile-amount-item">
                <dt>{{ tr('个人限额') }}</dt>
                <dd>{{ money(limit) }}</dd>
              </div>
              <div v-if="remaining != null" class="profile-amount-item">
                <dt>{{ tr('剩余个人额度') }}</dt>
                <dd>{{ money(remaining) }}</dd>
              </div>
            </dl>
          </template>
          <p v-else class="profile-copy">{{ tr('选择团队后可查看你的消费。') }}</p>
        </div>
      </section>

      <!-- 其他团队：只列当前团队之外的团队。切换后，新团队进入顶部摘要，原团队回到列表。有停用或禁用状态的团队仍显示原因，但不可切换。只有一个团队时省掉空列表，只留一句邀请链接提示。 -->
      <section class="profile-card profile-teams" aria-labelledby="profile-teams-title">
        <div class="profile-section-header">
          <h2 id="profile-teams-title">
            <UsersRound :size="18" aria-hidden="true" />
            {{ tr('其他团队') }}
            <span v-if="otherTeams.length" class="profile-count">{{ otherTeams.length }}</span>
          </h2>
        </div>

        <template v-if="otherTeams.length">
          <ul class="team-list">
            <li v-for="team in otherTeams" :key="team.team_id">
              <div class="team-info">
                <strong>{{ team.team_name }}</strong>
                <div class="profile-meta">
                  <span>{{ roleLabel(team.role) }}</span>
                  <span v-if="team.is_owner">{{ tr('个人团队') }}</span>
                  <span v-if="team.joined_at">{{ tr('加入于') }} {{ team.joined_at.slice(0, 10) }}</span>
                </div>
              </div>
              <span v-if="unavailable(team)" class="profile-badge is-neutral">{{ unavailable(team) }}</span>
              <AppButton
                v-else
                variant="secondary"
                size="sm"
                type="button"
                :aria-label="tr('切换到 {p0}', { p0: team.team_name })"
                @click="selectTeam(team)"
              >
                {{ tr('切换') }}
              </AppButton>
            </li>
          </ul>
          <p class="profile-copy">{{ tr('使用他人发出的邀请链接加入团队。') }}</p>
        </template>
        <p v-else class="profile-copy">{{ tr('使用他人发出的邀请链接加入团队。') }}</p>
      </section>

      <!-- 账号与安全：改成紧凑的设置行。器灵版将扫码方式和绑定状态合到一行，待绑定时保留绑定入口。密码版保留可展开的改密表单。退出登录放在安全区末尾，协议和数据申请放在页脚。 -->
      <section class="profile-card profile-security" aria-labelledby="profile-security-title">
        <div class="profile-section-header">
          <h2 id="profile-security-title">
            <ShieldCheck :size="18" aria-hidden="true" />
            {{ tr('账号与安全') }}
          </h2>
        </div>

        <div class="profile-security-rows">
          <template v-if="auth.provider === 'qiling'">
            <div class="profile-security-row">
              <div class="profile-security-meta">
                <span class="profile-security-label">{{ tr('器灵微信扫码') }}</span>
              </div>
              <div class="profile-security-state">
                <span class="profile-badge" :class="auth.qilingBound ? 'is-neutral' : 'is-warning'">
                  {{ auth.qilingBound ? tr('已绑定') : tr('待绑定') }}
                </span>
              </div>
            </div>
            <div v-if="auth.qilingEnabled && !auth.qilingBound" class="profile-qiling-box">
              <QilingLogin bind @bound="qilingBound" />
            </div>
          </template>

          <template v-else>
            <div class="profile-security-row">
              <span class="profile-security-label">{{ tr('登录方式') }}</span>
              <span class="profile-security-val">{{ tr('账号密码') }}</span>
            </div>
            <details class="profile-password">
              <summary>{{ tr('修改密码') }}</summary>
              <form class="password-form" @submit.prevent="changePassword">
                <label>
                  {{ tr('当前密码') }}
                  <input v-model="passwordForm.oldPassword" type="password" autocomplete="current-password" required :disabled="changing" />
                </label>
                <label>
                  {{ tr('新密码（至少 8 位）') }}
                  <input v-model="passwordForm.newPassword" type="password" autocomplete="new-password" required minlength="8" :disabled="changing" />
                </label>
                <label>
                  {{ tr('确认新密码') }}
                  <input v-model="passwordForm.confirmPassword" type="password" autocomplete="new-password" required minlength="8" :disabled="changing" />
                </label>
                <AppButton type="submit" variant="primary" :loading="changing">{{ tr('修改密码') }}</AppButton>
              </form>
            </details>
          </template>

          <div class="profile-logout-wrap">
            <AppButton
              class="profile-logout logout-button"
              type="button"
              variant="ghost"
              size="sm"
              :loading="signingOut"
              @click="logout"
            >
              <LogOut :size="15" aria-hidden="true" />
              {{ tr('退出登录') }}
            </AppButton>
          </div>
        </div>
      </section>
    </div>

    <!-- 团队充值弹窗 -->
    <div v-if="showTopUpModal" class="profile-modal-backdrop" @click.self="closeTopUpModal">
      <div class="profile-modal-card" role="dialog" aria-modal="true" :aria-label="tr('团队充值')">
        <div class="profile-modal-header">
          <h3 class="profile-modal-title">
            <CreditCard :size="18" aria-hidden="true" />
            {{ tr('团队充值') }}
          </h3>
          <button class="profile-modal-close" type="button" :aria-label="tr('关闭')" @click="closeTopUpModal">
            <X :size="18" aria-hidden="true" />
          </button>
        </div>

        <div class="profile-modal-body">
          <div class="profile-topup-team-info">
            <span class="profile-topup-label">{{ tr('充值目标团队') }}</span>
            <strong class="profile-topup-team-name">{{ current?.team_name }}</strong>
            <span class="profile-topup-current-bal">{{ tr('当前团队余额：{p0}', { p0: money(current?.team_balance) }) }}</span>
          </div>

          <!-- Step 1: 充值表单（微信扫码或超管直接到账） -->
          <template v-if="topUpStep === 'form'">
            <form class="profile-topup-form" @submit.prevent="handleTopUpSubmit">
              <div v-if="auth.isSuperAdmin" class="profile-topup-mode-selector">
                <label class="profile-radio-label">
                  <input v-model="topUpMode" type="radio" value="wechat" />
                  <span>{{ tr('微信支付（线上扫码）') }}</span>
                </label>
                <label class="profile-radio-label">
                  <input v-model="topUpMode" type="radio" value="direct" />
                  <span>{{ tr('管理员人工充值（直接到账）') }}</span>
                </label>
              </div>

              <div class="profile-preset-amounts">
                <button
                  v-for="amt in [50, 100, 200, 500, 1000]"
                  :key="amt"
                  type="button"
                  class="profile-preset-btn"
                  :class="{ 'is-active': topUpAmount === amt }"
                  @click="selectPresetAmount(amt)"
                >
                  ¥ {{ amt }}
                </button>
              </div>

              <label class="profile-topup-field">
                <span>{{ tr('充值金额（元）') }}</span>
                <input
                  v-model.number="topUpAmount"
                  type="number"
                  min="1"
                  step="0.01"
                  required
                  placeholder="0.00"
                  :disabled="topUpSubmitting"
                />
              </label>

              <label class="profile-topup-field">
                <span>{{ tr('备注说明（可选）') }}</span>
                <input
                  v-model="topUpNote"
                  type="text"
                  placeholder="如：线上充值 / 平台赠送"
                  :disabled="topUpSubmitting"
                />
              </label>

              <div class="profile-modal-actions">
                <AppButton variant="secondary" size="sm" type="button" :disabled="topUpSubmitting" @click="closeTopUpModal">
                  {{ tr('取消') }}
                </AppButton>
                <AppButton variant="primary" size="sm" type="submit" :loading="topUpSubmitting">
                  {{ topUpMode === 'direct' ? tr('确认充值') : tr('微信支付充值') }}
                </AppButton>
              </div>
            </form>
          </template>

          <!-- Step 2: 微信扫码支付中 -->
          <template v-else-if="topUpStep === 'qrcode'">
            <div class="profile-qrcode-box">
              <div class="profile-qrcode-header">
                <span class="profile-qrcode-amount">¥ {{ Number(currentOrder?.amount || topUpAmount).toFixed(2) }}</span>
                <span class="profile-qrcode-order-no">{{ tr('订单号：{p0}', { p0: currentOrder?.out_trade_no }) }}</span>
              </div>

              <div class="profile-qrcode-container">
                <div v-if="qrCodeLoading" class="profile-qrcode-loading">
                  <LoaderCircle class="is-spinning" :size="32" aria-hidden="true" />
                  <span>{{ tr('正在生成支付二维码…') }}</span>
                </div>
                <img v-else-if="qrCodeDataUrl" :src="qrCodeDataUrl" :alt="tr('微信支付二维码')" class="profile-qrcode-img" />
                <div v-else class="profile-qrcode-failed">
                  <p>{{ tr('二维码生成失败，请稍后重试') }}</p>
                </div>
              </div>

              <div class="profile-qrcode-footer">
                <p class="profile-qrcode-tip">
                  <QrCode :size="16" aria-hidden="true" />
                  {{ tr('请使用手机微信扫一扫完成支付') }}
                </p>
                <p class="profile-qrcode-subtip">{{ tr('支付成功后自动到账，请勿关闭页面') }}</p>
              </div>

              <div class="profile-modal-actions">
                <AppButton variant="secondary" size="sm" type="button" @click="topUpStep = 'form'; stopPolling()">
                  {{ tr('返回修改金额') }}
                </AppButton>
                <!-- 若在 mock 模式下提供模拟支付测试按钮 -->
                <AppButton
                  v-if="currentOrder?.code_url?.includes('mock_')"
                  variant="primary"
                  size="sm"
                  type="button"
                  @click="triggerMockPay"
                >
                  {{ tr('[测试] 模拟微信支付成功') }}
                </AppButton>
                <AppButton variant="secondary" size="sm" type="button" @click="closeTopUpModal">
                  {{ tr('关闭') }}
                </AppButton>
              </div>
            </div>
          </template>

          <!-- Step 3: 支付成功 -->
          <template v-else-if="topUpStep === 'success'">
            <div class="profile-topup-success">
              <CheckCircle2 :size="48" class="profile-success-icon" aria-hidden="true" />
              <h4>{{ tr('充值成功') }}</h4>
              <p class="profile-success-amount">
                + ¥ {{ Number(topUpPaidDetail?.amount || topUpAmount).toFixed(2) }}
              </p>
              <p class="profile-success-bal">
                {{ tr('当前团队余额：{p0}', { p0: money(topUpPaidDetail?.balance ?? current?.team_balance) }) }}
              </p>
              <div class="profile-modal-actions">
                <AppButton variant="primary" size="sm" type="button" @click="closeTopUpModal">
                  {{ tr('完成') }}
                </AppButton>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- 页脚：协议和数据申请放在页脚 -->
    <footer v-if="auth.legalReady" class="profile-footer">
      <FileText :size="15" aria-hidden="true" />
      <a :href="API_BASE + '/auth/legal/terms'" target="_blank" rel="noopener noreferrer">{{ tr('用户协议') }}</a>
      <a :href="API_BASE + '/auth/legal/privacy'" target="_blank" rel="noopener noreferrer">{{ tr('隐私政策') }}</a>
      <a :href="API_BASE + '/auth/legal/privacy#account-data-requests'" target="_blank" rel="noopener noreferrer">{{ tr('账号与数据申请') }}</a>
    </footer>
  </main>
</template>

<style scoped>
.profile-page {
  max-width: 880px;
  margin-inline: auto;
  padding: 28px 20px 48px;
  color: var(--app-text);
}

.profile-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
  padding: 20px 22px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 16px;
}

.profile-avatar {
  display: grid;
  place-items: center;
  flex: 0 0 54px;
  height: 54px;
  overflow: hidden;
  border-radius: 14px;
  background: var(--app-accent-soft);
  color: var(--app-accent);
  font-size: 22px;
  font-weight: 700;
}

.profile-avatar-editor { position: relative; flex: 0 0 54px; }
.profile-avatar-change { position: absolute; right: -5px; bottom: -5px; display: grid; place-items: center; width: 25px; height: 25px; padding: 0; border: 2px solid var(--app-surface); border-radius: 50%; color: var(--app-surface); background: var(--app-accent); cursor: pointer; }
.profile-avatar-change:hover:not(:disabled) { filter: brightness(1.1); }
.profile-avatar-change:focus-visible, .profile-nickname-form input:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 3px; }
.profile-avatar-change:disabled { opacity: .55; cursor: not-allowed; }
.profile-avatar-change .is-spinning { animation: avatar-spin 1s linear infinite; }
@keyframes avatar-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .profile-avatar-change .is-spinning { animation: none; } }
.profile-avatar-input { display: none; }
.profile-nickname-form { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 8px; }
.profile-nickname-form input { width: min(220px, 100%); min-width: 0; height: 34px; padding: 0 10px; border: 1px solid var(--app-border); border-radius: 8px; background: var(--app-surface); color: var(--app-text); font: inherit; }
.profile-nickname-form input:disabled { opacity: .6; }

.profile-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.profile-identity,
.team-info {
  flex: 1;
  min-width: 0;
}

.profile-caption {
  margin: 0 0 3px;
  color: var(--app-text-secondary);
  font-size: 12px;
}

.profile-name-line,
.profile-meta,
.profile-badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.profile-identity h1 {
  margin: 0;
  font-size: clamp(20px, 2.6vw, 24px);
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.profile-meta {
  color: var(--app-text-secondary);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.profile-identity .profile-meta {
  margin-top: 6px;
}

/* 单列布局容器 */
.profile-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.profile-card {
  min-width: 0;
  padding: 20px 22px;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  background: var(--app-surface);
}

.profile-section-header h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 14px;
  font-size: 15px;
  font-weight: 650;
  color: var(--app-text);
}

.profile-section-header h2 svg {
  color: var(--app-accent);
}

/* 团队与消费合成卡片 */
.profile-team-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
}

.profile-team-identity {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.profile-team-name {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.3;
  overflow-wrap: anywhere;
  color: var(--app-text);
}

.profile-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.profile-link,
.profile-text-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  text-decoration: none;
  font-size: 13px;
}

.profile-link {
  padding: 0 12px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  color: var(--app-text);
  background: var(--app-surface-muted);
  transition: all .15s ease;
}

.profile-link.is-primary {
  color: var(--app-accent);
  border-color: transparent;
  background: var(--app-accent-soft);
  font-weight: 650;
}

.profile-link:hover,
.profile-link.is-primary:hover {
  border-color: var(--app-border-strong);
  background: var(--app-surface-hover);
}

.profile-divider {
  height: 1px;
  background: var(--app-border);
  margin: 18px 0 16px;
}

/* 消费区域：按行展示指标 */
.profile-spend-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.profile-subheading {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin: 0;
  font-size: 14px;
  font-weight: 650;
  color: var(--app-text);
}

.profile-subheading svg {
  color: var(--app-accent);
}

.profile-text-link {
  color: var(--app-accent);
  font-size: 13px;
  font-weight: 550;
}

.profile-text-link:hover {
  text-decoration: underline;
}

.profile-amounts-line {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 14px 28px;
  margin: 0;
  padding: 0;
}

.profile-amount-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 130px;
}

.profile-amount-item dt {
  color: var(--app-text-secondary);
  font-size: 12px;
}

.profile-amount-item dd {
  margin: 0;
  font-size: 16px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
  color: var(--app-text);
}

.profile-amount-item.is-cost dd {
  color: var(--app-accent);
  font-size: 20px;
  font-weight: 700;
}

.profile-balance-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.profile-topup-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 11px;
}

/* 徽章与标签 */
.profile-badge,
.profile-count {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--app-accent-soft);
  color: var(--app-accent);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.profile-badge.is-neutral,
.profile-count {
  color: var(--app-text-secondary);
  background: var(--app-surface-muted);
}

.profile-badge.is-warning {
  color: #c27d19;
  background: rgb(245 158 11 / 14%);
}

.profile-copy {
  margin: 8px 0 0;
  color: var(--app-text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

/* 其他团队列表 */
.team-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.team-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-surface);
}

.team-info strong {
  display: block;
  margin-bottom: 3px;
  font-size: 14px;
  overflow-wrap: anywhere;
}

.team-list + .profile-copy {
  margin-top: 12px;
}

/* 账号与安全：紧凑设置行 */
.profile-security-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.profile-security-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
  padding: 8px 0;
  font-size: 13px;
  border-bottom: 1px solid var(--app-border);
}

.profile-security-label {
  color: var(--app-text);
  font-weight: 550;
}

.profile-security-val {
  color: var(--app-text-secondary);
}

.profile-qiling-box {
  margin-top: 4px;
  padding: 12px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-surface-muted);
}

.profile-password {
  padding-block: 4px;
}

.profile-password summary {
  width: fit-content;
  padding-block: 4px;
  cursor: pointer;
  color: var(--app-accent);
  font-size: 13px;
  font-weight: 550;
}

.password-form {
  display: grid;
  gap: 10px;
  margin-top: 8px;
  max-width: 360px;
}

.password-form label {
  display: grid;
  gap: 5px;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.password-form input {
  width: 100%;
  min-height: 36px;
  padding: 0 10px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  color: var(--app-text);
  background: var(--app-surface-muted);
}

.profile-logout-wrap {
  display: flex;
  justify-content: flex-start;
  padding-top: 6px;
}

.profile-logout {
  color: var(--creation-danger);
}

/* 团队充值弹窗样式 */
.profile-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgb(0 0 0 / 52%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.profile-modal-card {
  width: 100%;
  max-width: 440px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 16px;
  box-shadow: 0 16px 40px rgb(0 0 0 / 22%);
  overflow: hidden;
}

.profile-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--app-border);
}

.profile-modal-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 16px;
  font-weight: 650;
  color: var(--app-text);
}

.profile-modal-title svg {
  color: var(--app-accent);
}

.profile-modal-close {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--app-text-secondary);
  border-radius: 6px;
  cursor: pointer;
  transition: all .15s ease;
}

.profile-modal-close:hover {
  background: var(--app-surface-hover);
  color: var(--app-text);
}

.profile-modal-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.profile-topup-team-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  background: var(--app-surface-muted);
  border: 1px solid var(--app-border);
  border-radius: 10px;
}

.profile-topup-label {
  font-size: 11px;
  color: var(--app-text-secondary);
}

.profile-topup-team-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--app-text);
}

.profile-topup-current-bal {
  font-size: 13px;
  color: var(--app-accent);
  font-weight: 600;
}

.profile-topup-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.profile-preset-amounts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.profile-preset-btn {
  flex: 1 1 calc(20% - 8px);
  min-width: 60px;
  padding: 8px 0;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface);
  color: var(--app-text);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all .15s ease;
}

.profile-preset-btn:hover {
  border-color: var(--app-border-strong);
  background: var(--app-surface-hover);
}

.profile-preset-btn.is-active {
  border-color: var(--app-accent);
  background: var(--app-accent-soft);
  color: var(--app-accent);
}

.profile-topup-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--app-text-secondary);
}

.profile-topup-field input {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface-muted);
  color: var(--app-text);
  font-size: 14px;
}

.profile-modal-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 6px;
}

.profile-topup-contact {
  font-size: 13px;
  line-height: 1.6;
  color: var(--app-text-secondary);
}

.profile-topup-mode-selector {
  display: flex;
  gap: 16px;
  padding: 8px 12px;
  border: 1px dashed var(--app-border);
  border-radius: 8px;
  background: var(--app-surface-muted);
}

.profile-radio-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--app-text);
  cursor: pointer;
}

.profile-radio-label input {
  cursor: pointer;
}

.profile-qrcode-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 8px 0;
  text-align: center;
}

.profile-qrcode-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.profile-qrcode-amount {
  font-size: 28px;
  font-weight: 800;
  color: var(--app-accent);
}

.profile-qrcode-order-no {
  font-size: 12px;
  color: var(--app-text-secondary);
  font-family: monospace;
}

.profile-qrcode-container {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 236px;
  height: 236px;
  padding: 8px;
  background: #ffffff;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.profile-qrcode-img {
  width: 220px;
  height: 220px;
  object-fit: contain;
  display: block;
}

.profile-qrcode-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #333333;
  font-size: 12px;
}

.profile-qrcode-loading .is-spinning {
  animation: spin 1s linear infinite;
  color: var(--app-accent, #6366f1);
}

.profile-qrcode-failed {
  color: #ef4444;
  font-size: 12px;
  padding: 20px;
}

.profile-qrcode-footer {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.profile-qrcode-tip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--app-text);
  margin: 0;
}

.profile-qrcode-tip svg {
  color: #07c160; /* WeChat Green */
}

.profile-qrcode-subtip {
  font-size: 12px;
  color: var(--app-text-secondary);
  margin: 0;
}

.profile-topup-success {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 16px 0;
  text-align: center;
}

.profile-success-icon {
  color: #10b981;
}

.profile-topup-success h4 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--app-text);
}

.profile-success-amount {
  margin: 0;
  font-size: 26px;
  font-weight: 800;
  color: #10b981;
}

.profile-success-bal {
  margin: 0;
  font-size: 13px;
  color: var(--app-text-secondary);
}

/* 页脚 */
.profile-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  margin-top: 20px;
  padding-inline: 4px;
  color: var(--app-text-secondary);
  font-size: 12px;
}

.profile-footer a {
  color: inherit;
  text-decoration: none;
}

.profile-footer a:hover {
  color: var(--app-accent);
  text-decoration: underline;
}

.profile-state {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  color: var(--app-text-secondary);
}

.profile-page :is(a, button, input, summary):focus-visible {
  outline: 2px solid var(--app-accent);
  outline-offset: 2px;
}

@media (max-width: 640px) {
  .profile-page {
    padding: 16px 14px 36px;
  }

  .profile-header {
    padding: 14px 16px;
  }

  .profile-card {
    padding: 16px;
  }

  .profile-team-summary {
    flex-direction: column;
    align-items: flex-start;
  }

  .profile-actions {
    width: 100%;
  }

  .profile-actions .profile-link {
    flex: 1;
    justify-content: center;
  }

  .profile-amounts-line {
    flex-direction: column;
    gap: 10px;
  }

  .profile-amount-item {
    width: 100%;
  }
}
</style>
