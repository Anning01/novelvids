<script setup lang="ts">
import { tr } from '@/i18n'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '@/api'
import AppButton from '@/components/AppButton.vue'
import AppPagination from '@/components/AppPagination.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { notice } from '@/shared/notice'
import type { RechargeOrderItem } from '@/types'
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  CreditCard,
  LoaderCircle,
  QrCode,
  Receipt,
  RefreshCw,
  RotateCcw,
  Search,
  X,
  XCircle,
} from 'lucide-vue-next'

const auth = useAuthStore()

const orders = ref<RechargeOrderItem[]>([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const totalOrders = ref(0)
const selectedStatus = ref('')
const searchKeyword = ref('')
const syncingOrderNo = ref<string | null>(null)
const copiedOrderNo = ref<string | null>(null)

// 待支付订单弹出扫码支付弹窗
const payingOrder = ref<RechargeOrderItem | null>(null)
const qrCodeDataUrl = ref('')
const qrCodeLoading = ref(false)
const remainingSeconds = ref(0)
let pollTimer: ReturnType<typeof setInterval> | null = null
let countdownTimer: ReturnType<typeof setInterval> | null = null

// 超级管理员退款弹窗状态
const refundingOrder = ref<RechargeOrderItem | null>(null)
const refundReason = ref('')
const refundSubmitting = ref(false)

const statusFilters = [
  { value: '', label: tr('全部') },
  { value: 'pending', label: tr('待支付') },
  { value: 'paid', label: tr('已支付') },
  { value: 'refunding', label: tr('退款处理中') },
  { value: 'refunded', label: tr('已退款') },
  { value: 'refund_closed', label: tr('退款已关闭') },
  { value: 'expired', label: tr('已过期') },
  { value: 'closed', label: tr('已关闭') },
]

function statusMeta(status: string) {
  switch (status) {
    case 'paid':
      return { label: tr('已支付'), className: 'is-paid', icon: CheckCircle2 }
    case 'refunding':
      return { label: tr('退款处理中'), className: 'is-pending', icon: Clock }
    case 'refund_closed':
      return { label: tr('退款已关闭'), className: 'is-closed', icon: XCircle }
    case 'refunded':
      return { label: tr('已退款'), className: 'is-refunded', icon: RotateCcw }
    case 'pending':
      return { label: tr('待支付'), className: 'is-pending', icon: Clock }
    case 'expired':
      return { label: tr('已过期'), className: 'is-expired', icon: XCircle }
    case 'closed':
      return { label: tr('已关闭'), className: 'is-closed', icon: XCircle }
    case 'failed':
      return { label: tr('支付失败'), className: 'is-failed', icon: XCircle }
    default:
      return { label: status, className: 'is-default', icon: Clock }
  }
}

function formatMoney(amount: number | string) {
  const val = Number(amount)
  return Number.isFinite(val) ? val.toFixed(2) : '0.00'
}

function formatUserDisplay(nickname?: string | null, username?: string | null) {
  if (nickname) return nickname
  if (!username) return '-'
  if (username.startsWith('qiling-')) return tr('微信用户')
  return username
}

function formatDate(isoStr?: string | null) {
  if (!isoStr) return '-'
  try {
    const d = new Date(isoStr)
    if (Number.isNaN(d.getTime())) return isoStr
    return d.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return isoStr
  }
}

async function loadOrders() {
  loading.value = true
  try {
    const res = await api.rechargeOrders({
      page: page.value,
      page_size: pageSize.value,
      status: selectedStatus.value || undefined,
      search: searchKeyword.value.trim() || undefined,
    })
    orders.value = res.data?.items ?? []
    totalOrders.value = res.data?.pagination?.total ?? (res.data as unknown as { total?: number })?.total ?? orders.value.length
    if (!orders.value.length && page.value > 1) {
      page.value -= 1
      await loadOrders()
    }
  } catch (err) {
    notice.error(err instanceof Error ? err.message : tr('加载订单失败'))
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  void loadOrders()
}

function handleStatusFilter(val: string) {
  if (selectedStatus.value === val) return
  selectedStatus.value = val
  page.value = 1
  void loadOrders()
}

function changePage(next: number) {
  page.value = next
  void loadOrders()
}

function changePageSize(size: number) {
  pageSize.value = size
  page.value = 1
  void loadOrders()
}

async function handleCopy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedOrderNo.value = text
    setTimeout(() => {
      if (copiedOrderNo.value === text) copiedOrderNo.value = null
    }, 2000)
  } catch {
    notice.info(text)
  }
}

// 主动向微信平台查询订单最新状态并同步到本地
async function handleSync(order: RechargeOrderItem) {
  syncingOrderNo.value = order.out_trade_no
  try {
    const res = await api.syncRechargeOrder(order.out_trade_no)
    const detail = res.data
    order.status = detail.status
    order.paid_at = detail.paid_at
    order.transaction_id = detail.transaction_id

    if (detail.status === 'paid') {
      notice.success(tr('订单已完成支付，充值成功！'))
      await auth.refreshMe()
    } else if (detail.status === 'expired') {
      notice.info(tr('订单超过 15 分钟未支付，已自动关闭过期'))
    } else if (detail.status === 'closed') {
      notice.info(tr('订单已在微信端关闭'))
    } else {
      notice.info(tr('订单状态同步完成：当前为 {p0}', { p0: statusMeta(detail.status).label }))
    }
  } catch (err) {
    notice.error(err instanceof Error ? err.message : tr('同步订单状态失败'))
  } finally {
    syncingOrderNo.value = null
  }
}

// 打开扫码支付弹窗继续支付
async function openPayModal(order: RechargeOrderItem) {
  payingOrder.value = order
  qrCodeDataUrl.value = ''
  qrCodeLoading.value = true

  // 计算剩余秒数
  if (order.expires_at) {
    const expTime = new Date(order.expires_at).getTime()
    remainingSeconds.value = Math.max(0, Math.floor((expTime - Date.now()) / 1000))
  } else {
    remainingSeconds.value = 900 // 默认 15 分钟
  }

  // 生成二维码
  if (order.code_url) {
    try {
      const QRCode = (await import('qrcode')).default
      qrCodeDataUrl.value = await QRCode.toDataURL(order.code_url, {
        width: 220,
        margin: 1,
        color: { dark: '#000000', light: '#ffffff' },
      })
    } catch (err) {
      console.error('Failed to generate QR code', err)
    } finally {
      qrCodeLoading.value = false
    }
  } else {
    qrCodeLoading.value = false
  }

  startCountdown()
  startPolling(order.out_trade_no)
}

function closePayModal() {
  payingOrder.value = null
  stopPolling()
  stopCountdown()
}

function startCountdown() {
  stopCountdown()
  countdownTimer = setInterval(() => {
    if (remainingSeconds.value <= 1) {
      remainingSeconds.value = 0
      stopCountdown()
      if (payingOrder.value) {
        payingOrder.value.status = 'expired'
      }
    } else {
      remainingSeconds.value -= 1
    }
  }, 1000)
}

function stopCountdown() {
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
}

function startPolling(outTradeNo: string) {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      const res = await api.queryRechargeOrder(outTradeNo)
      if (res.data.status === 'paid') {
        stopPolling()
        stopCountdown()
        if (payingOrder.value) {
          payingOrder.value.status = 'paid'
        }
        notice.success(tr('支付成功！充值已到账'))
        await auth.refreshMe()
        await loadOrders()
        setTimeout(() => {
          closePayModal()
        }, 1500)
      } else if (res.data.status === 'expired' || res.data.status === 'closed') {
        stopPolling()
        if (payingOrder.value) {
          payingOrder.value.status = res.data.status
        }
      }
    } catch {
      // transient network error, keep polling
    }
  }, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const formattedCountdown = computed(() => {
  const mins = Math.floor(remainingSeconds.value / 60)
  const secs = remainingSeconds.value % 60
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
})

function openRefundModal(order: RechargeOrderItem) {
  refundingOrder.value = order
  refundReason.value = ''
}

function closeRefundModal() {
  if (refundSubmitting.value) return
  refundingOrder.value = null
  refundReason.value = ''
}

async function submitRefund() {
  if (!refundingOrder.value || refundSubmitting.value) return
  refundSubmitting.value = true
  try {
    const res = await api.refundRechargeOrder(refundingOrder.value.out_trade_no, {
      reason: refundReason.value.trim() || undefined,
    })
    if (res.data.status === 'refunded') notice.success(tr('退款成功，微信款项已原路退回并扣回团队余额'))
    else notice.info(tr('退款处理中，请同步订单确认结果'))
    refundingOrder.value.status = res.data.status
    refundingOrder.value.refund_id = res.data.refund_id
    refundingOrder.value.refund_reason = res.data.refund_reason
    refundingOrder.value.refunded_at = res.data.refunded_at
    refundingOrder.value = null
    refundReason.value = ''
    await loadOrders()
    await auth.refreshMe()
  } catch (err) {
    notice.error(err instanceof Error ? err.message : tr('退款失败'))
  } finally {
    refundSubmitting.value = false
  }
}

onMounted(() => {
  void loadOrders()
})

onUnmounted(() => {
  stopPolling()
  stopCountdown()
})
</script>

<template>
  <main class="orders-page" role="main">
    <header class="orders-header">
      <div class="orders-header-title">
        <div class="orders-title-row">
          <Receipt :size="24" class="orders-title-icon" aria-hidden="true" />
          <h1>{{ tr('订单管理') }}</h1>
        </div>
        <p class="orders-header-desc">
          <span v-if="auth.isSuperAdmin">{{ tr('全平台充值订单总览 · 主动查单与自动维护') }}</span>
          <span v-else>{{ tr('我的充值订单与支付状态记录') }}</span>
        </p>
      </div>
      <div class="orders-header-actions">
        <AppButton variant="secondary" size="sm" :loading="loading" @click="loadOrders">
          <RefreshCw :size="14" aria-hidden="true" />
          <span>{{ tr('刷新列表') }}</span>
        </AppButton>
      </div>
    </header>

    <!-- 筛选工具栏 -->
    <section class="orders-toolbar" :aria-label="tr('订单筛选与搜索')">
      <div class="orders-filter-tabs" role="tablist">
        <button
          v-for="item in statusFilters"
          :key="item.value"
          type="button"
          class="orders-tab-btn"
          :class="{ 'is-active': selectedStatus === item.value }"
          role="tab"
          :aria-selected="selectedStatus === item.value"
          @click="handleStatusFilter(item.value)"
        >
          {{ item.label }}
        </button>
      </div>

      <form class="orders-search-form" @submit.prevent="handleSearch">
        <div class="orders-search-input-wrap">
          <Search :size="16" class="orders-search-icon" aria-hidden="true" />
          <input
            v-model="searchKeyword"
            type="search"
            class="orders-search-input"
            :placeholder="auth.isSuperAdmin ? tr('搜索订单号 / 流水号 / 团队 / 用户 / 备注') : tr('搜索订单号 / 备注')"
          />
        </div>
        <AppButton variant="secondary" size="sm" type="submit">
          {{ tr('搜索') }}
        </AppButton>
      </form>
    </section>

    <!-- 订单列表主体表格 -->
    <section class="orders-panel" aria-labelledby="orders-list-heading">
      <h2 id="orders-list-heading" class="sr-only">{{ tr('充值订单列表') }}</h2>

      <div v-if="loading && !orders.length" class="orders-loading-state">
        <LoaderCircle class="is-spinning" :size="32" aria-hidden="true" />
        <span>{{ tr('正在加载订单数据…') }}</span>
      </div>

      <div v-else-if="!orders.length" class="orders-empty-state">
        <Receipt :size="48" class="orders-empty-icon" aria-hidden="true" />
        <p class="orders-empty-text">{{ tr('暂无符合条件的充值订单') }}</p>
        <span class="orders-empty-subtext">{{ tr('充值订单支持待支付15分钟自动超时维护') }}</span>
      </div>

      <div v-else class="orders-table-wrapper">
        <table class="orders-table">
          <thead>
            <tr>
              <th>{{ tr('商户订单号') }}</th>
              <th>{{ tr('充值目标团队') }}</th>
              <th v-if="auth.isSuperAdmin">{{ tr('充值用户') }}</th>
              <th>{{ tr('充值金额') }}</th>
              <th>{{ tr('支付方式') }}</th>
              <th>{{ tr('订单状态') }}</th>
              <th>{{ tr('创建时间') }}</th>
              <th>{{ tr('支付时间') }}</th>
              <th class="actions-header">{{ tr('操作') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="order in orders" :key="order.id" class="orders-table-row">
              <td class="col-orderno">
                <div class="order-no-cell">
                  <span class="order-no-text" :title="order.out_trade_no">{{ order.out_trade_no }}</span>
                  <button
                    type="button"
                    class="copy-btn"
                    :aria-label="tr('复制订单号')"
                    :title="tr('复制订单号')"
                    @click="handleCopy(order.out_trade_no)"
                  >
                    <Check v-if="copiedOrderNo === order.out_trade_no" :size="13" class="is-copied" />
                    <Copy v-else :size="13" />
                  </button>
                </div>
                <div v-if="order.note" class="order-note-text" :title="order.note">{{ order.note }}</div>
              </td>

              <td class="col-team">
                <span class="team-name">{{ order.team_name || '-' }}</span>
              </td>

              <td v-if="auth.isSuperAdmin" class="col-user">
                <div class="user-info-cell">
                  <span class="user-nickname">{{ formatUserDisplay(order.nickname, order.username) }}</span>
                </div>
              </td>

              <td class="col-amount">
                <span class="amount-val">¥ {{ formatMoney(order.amount) }}</span>
              </td>

              <td class="col-method">
                <span class="method-tag">{{ tr('微信支付') }}</span>
              </td>

              <td class="col-status">
                <span class="status-badge" :class="statusMeta(order.status).className">
                  <component :is="statusMeta(order.status).icon" :size="12" class="status-icon" aria-hidden="true" />
                  <span>{{ statusMeta(order.status).label }}</span>
                </span>
              </td>

              <td class="col-time">{{ formatDate(order.created_at) }}</td>
              <td class="col-time">{{ formatDate(order.paid_at) }}</td>

              <td class="col-actions">
                <div class="actions-group">
                  <!-- 待支付订单且有二维码URL：支持继续扫码支付 -->
                  <AppButton
                    v-if="order.status === 'pending' && order.code_url"
                    variant="primary"
                    size="sm"
                    class="pay-btn"
                    @click="openPayModal(order)"
                  >
                    <QrCode :size="13" aria-hidden="true" />
                    <span>{{ tr('去支付') }}</span>
                  </AppButton>

                  <!-- 主动同步微信最新支付状态 -->
                  <AppButton
                    variant="ghost"
                    size="sm"
                    class="sync-btn"
                    :loading="syncingOrderNo === order.out_trade_no"
                    :title="tr('主动向微信商户平台查询支付状态')"
                    @click="handleSync(order)"
                  >
                    <RefreshCw :size="13" aria-hidden="true" />
                    <span>{{ tr('同步') }}</span>
                  </AppButton>

                  <!-- 超管退款 -->
                  <AppButton
                    v-if="auth.isSuperAdmin && ['paid', 'refunding'].includes(order.status)"
                    variant="ghost"
                    size="sm"
                    class="refund-btn"
                    :title="tr('微信原路退回并扣回团队余额')"
                    @click="openRefundModal(order)"
                  >
                    <RotateCcw :size="13" aria-hidden="true" />
                    <span>{{ tr('退款') }}</span>
                  </AppButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <div class="orders-pagination-wrap">
          <AppPagination
            :page="page"
            :page-size="pageSize"
            :total="totalOrders"
            @page-change="changePage"
            @size-change="changePageSize"
          />
        </div>
      </div>
    </section>

    <!-- 继续扫码付款弹窗 -->
    <div v-if="payingOrder" class="modal-backdrop" @click.self="closePayModal">
      <div class="pay-modal-card" role="dialog" aria-modal="true" :aria-label="tr('微信扫码支付')">
        <div class="pay-modal-header">
          <h3 class="pay-modal-title">
            <CreditCard :size="18" aria-hidden="true" />
            <span>{{ tr('微信扫码支付') }}</span>
          </h3>
          <button type="button" class="modal-close-btn" :aria-label="tr('关闭')" @click="closePayModal">
            <X :size="18" aria-hidden="true" />
          </button>
        </div>

        <div class="pay-modal-body">
          <div class="pay-info-summary">
            <span class="pay-amount-display">¥ {{ formatMoney(payingOrder.amount) }}</span>
            <span class="pay-orderno-text">{{ tr('订单号：{p0}', { p0: payingOrder.out_trade_no }) }}</span>
            <span class="pay-team-text">{{ tr('充值目标：{p0}', { p0: payingOrder.team_name }) }}</span>
          </div>

          <div v-if="payingOrder.status === 'paid'" class="pay-state-success">
            <CheckCircle2 :size="54" class="success-icon" />
            <h4>{{ tr('支付成功！') }}</h4>
            <p>{{ tr('团队余额已更新，正在关闭窗口…') }}</p>
          </div>

          <div v-else-if="payingOrder.status === 'expired' || remainingSeconds === 0" class="pay-state-expired">
            <XCircle :size="54" class="expired-icon" />
            <h4>{{ tr('订单已超时过期') }}</h4>
            <p>{{ tr('待支付订单有效时间为 15 分钟，请重新发起充值。') }}</p>
          </div>

          <div v-else class="qrcode-wrapper">
            <div v-if="qrCodeLoading" class="qrcode-loading">
              <LoaderCircle class="is-spinning" :size="32" aria-hidden="true" />
              <span>{{ tr('正在加载二维码…') }}</span>
            </div>
            <img v-else-if="qrCodeDataUrl" :src="qrCodeDataUrl" :alt="tr('微信支付二维码')" class="qrcode-img" />
            <div v-else class="qrcode-fail">
              <p>{{ tr('未获取到二维码，请点击同步或重新下单') }}</p>
            </div>

            <div class="qrcode-instructions">
              <p class="qrcode-tip">
                <QrCode :size="16" aria-hidden="true" />
                {{ tr('请使用手机微信扫一扫完成支付') }}
              </p>
              <p class="qrcode-subtip">{{ tr('支付成功后自动到账，请勿关闭页面') }}</p>
              <div class="countdown-badge" :class="{ 'is-expiring': remainingSeconds < 180 }">
                <Clock :size="13" aria-hidden="true" />
                <span>{{ tr('订单有效期剩余：{p0}', { p0: formattedCountdown }) }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="pay-modal-footer">
          <AppButton variant="secondary" size="sm" @click="closePayModal">
            {{ tr('关闭') }}
          </AppButton>
          <AppButton
            v-if="payingOrder.status === 'pending' && remainingSeconds > 0"
            variant="ghost"
            size="sm"
            :loading="syncingOrderNo === payingOrder.out_trade_no"
            @click="handleSync(payingOrder)"
          >
            {{ tr('主动查询支付结果') }}
          </AppButton>
        </div>
      </div>
    </div>

    <!-- 超管退款确认弹窗 -->
    <div
      v-if="refundingOrder"
      class="pay-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="refund-modal-title"
      @click.self="closeRefundModal"
    >
      <div class="refund-modal-card">
        <div class="pay-modal-header">
          <div class="pay-modal-title-row">
            <RotateCcw :size="18" class="refund-title-icon" aria-hidden="true" />
            <h3 id="refund-modal-title">{{ tr('充值订单退款') }}</h3>
          </div>
          <button
            type="button"
            class="pay-modal-close"
            :aria-label="tr('关闭')"
            @click="closeRefundModal"
          >
            <X :size="18" />
          </button>
        </div>

        <div class="refund-modal-body">
          <div class="refund-warning-box">
            <AlertTriangle :size="20" class="refund-warning-icon" aria-hidden="true" />
            <div class="refund-warning-content">
              <strong>{{ tr('退款扣回说明') }}</strong>
              <p>
                {{
                  tr(
                    '确认后将向微信发起原路退款，并自动从「{p0}」扣回充值金额 ¥{p1}。若该团队当前可用余额不足以扣回，系统将拒绝退款。',
                    { p0: refundingOrder.team_name, p1: formatMoney(refundingOrder.amount) }
                  )
                }}
              </p>
            </div>
          </div>

          <div class="refund-order-details">
            <div class="refund-detail-row">
              <span class="detail-label">{{ tr('商户订单号') }}</span>
              <span class="detail-value font-mono">{{ refundingOrder.out_trade_no }}</span>
            </div>
            <div class="refund-detail-row">
              <span class="detail-label">{{ tr('充值目标团队') }}</span>
              <span class="detail-value">{{ refundingOrder.team_name }}</span>
            </div>
            <div class="refund-detail-row">
              <span class="detail-label">{{ tr('充值金额') }}</span>
              <span class="detail-value text-amount">¥ {{ formatMoney(refundingOrder.amount) }}</span>
            </div>
            <div v-if="refundingOrder.nickname || refundingOrder.username" class="refund-detail-row">
              <span class="detail-label">{{ tr('充值用户') }}</span>
              <span class="detail-value">{{ formatUserDisplay(refundingOrder.nickname, refundingOrder.username) }}</span>
            </div>
          </div>

          <div class="refund-reason-field">
            <label for="refund-reason-input" class="refund-reason-label">
              {{ tr('退款原因（可选）') }}
            </label>
            <input
              id="refund-reason-input"
              v-model="refundReason"
              type="text"
              class="refund-reason-input"
              maxlength="200"
              :placeholder="tr('如：用户协商退款 / 误操作充值')"
            />
          </div>
        </div>

        <div class="pay-modal-footer">
          <AppButton variant="secondary" size="sm" :disabled="refundSubmitting" @click="closeRefundModal">
            {{ tr('取消') }}
          </AppButton>
          <AppButton
            variant="danger"
            size="sm"
            :loading="refundSubmitting"
            @click="submitRefund"
          >
            {{ tr('确认退款并扣款') }}
          </AppButton>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.orders-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 28px 24px 48px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.orders-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.orders-header-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.orders-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.orders-title-icon {
  color: var(--app-accent, #5b5cf6);
}

.orders-header-title h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--app-text, #1e293b);
  letter-spacing: -0.02em;
}

.orders-header-desc {
  margin: 0;
  font-size: 13px;
  color: var(--app-text-muted, #64748b);
}

.orders-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.orders-filter-tabs {
  display: inline-flex;
  background: var(--app-surface-muted, #f1f5f9);
  padding: 3px;
  border-radius: 10px;
  border: 1px solid var(--app-border, #e2e8f0);
}

.orders-tab-btn {
  border: none;
  background: transparent;
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--app-text-muted, #64748b);
  cursor: pointer;
  transition: all 0.15s ease;
}

.orders-tab-btn:hover {
  color: var(--app-text, #1e293b);
}

.orders-tab-btn.is-active {
  background: var(--app-surface, #ffffff);
  color: var(--app-accent, #5b5cf6);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.orders-search-form {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-grow: 1;
  max-width: 420px;
}

.orders-search-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
}

.orders-search-icon {
  position: absolute;
  left: 10px;
  color: var(--app-text-muted, #94a3b8);
  pointer-events: none;
}

.orders-search-input {
  width: 100%;
  height: 36px;
  padding: 0 12px 0 34px;
  border: 1px solid var(--app-border, #e2e8f0);
  border-radius: 8px;
  background: var(--app-surface, #ffffff);
  color: var(--app-text, #1e293b);
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.orders-search-input:focus {
  border-color: var(--app-accent, #5b5cf6);
  box-shadow: 0 0 0 3px rgba(91, 92, 246, 0.15);
}

.orders-panel {
  background: var(--app-surface, #ffffff);
  border: 1px solid var(--app-border, #e2e8f0);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.orders-loading-state,
.orders-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 64px 24px;
  color: var(--app-text-muted, #64748b);
  font-size: 14px;
}

.orders-empty-icon {
  color: var(--app-border, #cbd5e1);
}

.orders-empty-text {
  margin: 0;
  font-weight: 600;
  color: var(--app-text, #1e293b);
}

.orders-empty-subtext {
  font-size: 12px;
  color: var(--app-text-muted, #94a3b8);
}

.orders-table-wrapper {
  overflow-x: auto;
}

.orders-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  color: var(--app-text, #1e293b);
  white-space: nowrap;
}

.orders-table th {
  text-align: left;
  padding: 12px 14px;
  background: var(--app-surface-muted, #f8fafc);
  border-bottom: 1px solid var(--app-border, #e2e8f0);
  font-weight: 600;
  font-size: 12px;
  color: var(--app-text-muted, #64748b);
}

.orders-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--app-border, #e2e8f0);
  vertical-align: middle;
}

.orders-table-row:hover {
  background: var(--app-surface-hover, #f8fafc);
}

.order-no-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.order-no-text {
  font-weight: 600;
  color: var(--app-text, #1e293b);
}

.copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  color: var(--app-text-muted, #94a3b8);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.copy-btn:hover {
  background: var(--app-surface-muted, #f1f5f9);
  color: var(--app-accent, #5b5cf6);
}

.is-copied {
  color: var(--app-success, #10b981);
}

.order-note-text {
  font-size: 11px;
  color: var(--app-text-muted, #94a3b8);
  margin-top: 2px;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.team-name {
  font-weight: 500;
}

.user-info-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}

.user-nickname {
  font-weight: 500;
}

.user-username {
  color: var(--app-text-muted, #94a3b8);
  font-size: 11px;
}

.amount-val {
  font-weight: 700;
  color: var(--app-text, #0f172a);
}

.method-tag {
  display: inline-block;
  padding: 2px 6px;
  background: rgba(16, 185, 129, 0.08);
  color: #059669;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.status-badge.is-paid {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}

.status-badge.is-refunded {
  background: rgba(139, 92, 246, 0.12);
  color: #7c3aed;
}

.status-badge.is-pending {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}

.status-badge.is-expired {
  background: rgba(100, 116, 139, 0.12);
  color: #64748b;
}

.status-badge.is-closed {
  background: rgba(100, 116, 139, 0.1);
  color: #64748b;
}

.status-badge.is-failed {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
}

.status-icon {
  flex-shrink: 0;
}

.col-time {
  font-size: 12px;
  color: var(--app-text-muted, #64748b);
}

.actions-header {
  text-align: right;
}

.col-actions {
  text-align: right;
}

.actions-group {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.orders-pagination-wrap {
  padding: 12px 18px;
  border-top: 1px solid var(--app-border, #e2e8f0);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border-width: 0;
}

/* 支付扫码弹窗 */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 16px;
}

.pay-modal-card {
  width: 100%;
  max-width: 400px;
  background: var(--app-surface, #ffffff);
  border-radius: 16px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
  border: 1px solid var(--app-border, #e2e8f0);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.pay-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--app-border, #e2e8f0);
}

.pay-modal-title {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--app-text, #1e293b);
}

.modal-close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--app-text-muted, #64748b);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.modal-close-btn:hover {
  background: var(--app-surface-muted, #f1f5f9);
  color: var(--app-text, #1e293b);
}

.pay-modal-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  text-align: center;
}

.pay-info-summary {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.pay-amount-display {
  font-size: 28px;
  font-weight: 800;
  color: var(--app-accent, #5b5cf6);
  letter-spacing: -0.02em;
}

.pay-orderno-text,
.pay-team-text {
  font-size: 12px;
  color: var(--app-text-muted, #64748b);
}

.pay-state-success,
.pay-state-expired {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px 0;
}

.pay-state-success h4,
.pay-state-expired h4 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
}

.pay-state-success p,
.pay-state-expired p {
  margin: 0;
  font-size: 13px;
  color: var(--app-text-muted, #64748b);
}

.success-icon {
  color: var(--app-success, #10b981);
}

.expired-icon {
  color: var(--app-danger, #ef4444);
}

.qrcode-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}

.qrcode-loading,
.qrcode-fail {
  width: 220px;
  height: 220px;
  border-radius: 12px;
  background: var(--app-surface-muted, #f8fafc);
  border: 1px dashed var(--app-border, #cbd5e1);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--app-text-muted, #64748b);
  font-size: 13px;
}

.qrcode-img {
  width: 220px;
  height: 220px;
  border-radius: 12px;
  border: 1px solid var(--app-border, #e2e8f0);
  background: #ffffff;
  padding: 8px;
}

.qrcode-instructions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.qrcode-tip {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--app-text, #1e293b);
}

.qrcode-subtip {
  margin: 0;
  font-size: 12px;
  color: var(--app-text-muted, #64748b);
}

.countdown-badge {
  margin-top: 6px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  background: var(--app-surface-muted, #f1f5f9);
  color: var(--app-text-muted, #64748b);
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
}

.countdown-badge.is-expiring {
  background: rgba(239, 68, 68, 0.1);
  color: #dc2626;
}

.pay-modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--app-border, #e2e8f0);
  background: var(--app-surface-muted, #f8fafc);
}

.refund-btn {
  color: var(--app-text-muted, #64748b);
}

.refund-btn:hover {
  color: var(--app-danger, #ef4444);
  background: rgba(239, 68, 68, 0.08);
}

.refund-modal-card {
  width: 100%;
  max-width: 460px;
  background: var(--app-surface, #ffffff);
  border-radius: 16px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
  border: 1px solid var(--app-border, #e2e8f0);
  overflow: hidden;
  animation: modal-enter 0.2s ease-out;
}

.refund-title-icon {
  color: var(--app-danger, #ef4444);
}

.refund-modal-body {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.refund-warning-box {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
  color: #b91c1c;
}

.refund-warning-icon {
  flex-shrink: 0;
  margin-top: 1px;
}

.refund-warning-content strong {
  display: block;
  font-size: 13px;
  margin-bottom: 2px;
}

.refund-warning-content p {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--app-text, #1e293b);
}

.refund-order-details {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  background: var(--app-surface-muted, #f8fafc);
  border: 1px solid var(--app-border, #e2e8f0);
  border-radius: 8px;
  font-size: 13px;
}

.refund-detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.detail-label {
  color: var(--app-text-muted, #64748b);
}

.detail-value {
  font-weight: 500;
  color: var(--app-text, #1e293b);
}

.detail-value.font-mono {
  font-family: monospace;
  font-size: 12px;
}

.detail-value.text-amount {
  font-weight: 700;
  color: var(--app-danger, #ef4444);
}

.refund-reason-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.refund-reason-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--app-text, #1e293b);
}

.refund-reason-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--app-border, #e2e8f0);
  border-radius: 6px;
  font-size: 13px;
  background: var(--app-surface, #ffffff);
  color: var(--app-text, #0f172a);
  outline: none;
  box-sizing: border-box;
}

.refund-reason-input:focus {
  border-color: var(--app-accent, #5b5cf6);
  box-shadow: 0 0 0 2px rgba(91, 92, 246, 0.15);
}

.is-spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
