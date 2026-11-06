<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowUpRight, RefreshCw } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { api } from '@/api'
import { tr } from '@/i18n'
import { useAuthStore } from './authStore'
import type { LoginResult, QilingAttempt } from '@/types'

const props = defineProps<{ bind?: boolean; autoStart?: boolean }>()
const emit = defineEmits<{ authenticated: [session: LoginResult]; bound: [] }>()
const auth = useAuthStore()
const attempt = ref<QilingAttempt>()
const qrImage = ref('')
const qrUnavailable = ref(false)
const expired = ref(false)
const secondsLeft = ref(0)
const busy = ref(false)
const error = ref('')
const countdown = computed(() => `${Math.floor(secondsLeft.value / 60)}:${String(secondsLeft.value % 60).padStart(2, '0')}`)
let operation: AbortController | undefined
let pollTimer: ReturnType<typeof setTimeout> | undefined
let clockTimer: ReturnType<typeof setInterval> | undefined

function stopRequests() {
  operation?.abort()
  clearTimeout(pollTimer)
  clearInterval(clockTimer)
  operation = undefined
}

function stop() {
  stopRequests()
  attempt.value = undefined
  qrImage.value = ''
  qrUnavailable.value = false
  expired.value = false
  secondsLeft.value = 0
  busy.value = false
}

function expire() {
  stopRequests()
  expired.value = true
  secondsLeft.value = 0
  busy.value = false
}

async function start() {
  if (busy.value) return
  stopRequests()
  error.value = ''
  busy.value = true
  const current = new AbortController()
  const token = auth.token
  operation = current
  const active = () => !current.signal.aborted && auth.token === token
  try {
    const result = (await api.qilingStart(Boolean(props.bind))).data
    if (!active()) return
    const deadline = Date.now() + result.expires_in * 1000
    const tick = () => {
      secondsLeft.value = Math.max(0, Math.ceil((deadline - Date.now()) / 1000))
      if (secondsLeft.value === 0) expire()
    }
    tick()
    if (!active()) return
    clockTimer = setInterval(tick, 1000)
    attempt.value = result
    qrUnavailable.value = false
    await import('qrcode')
      .then(({ toDataURL }) => toDataURL(result.authorization_url, { width: 224, margin: 4 }))
      .then(image => { if (active()) qrImage.value = image })
      .catch(() => {
        if (active()) {
          qrImage.value = ''
          qrUnavailable.value = true
        }
      })
    if (!active()) return
    expired.value = false
    busy.value = false
    const poll = async () => {
      if (!active()) return
      try {
        tick()
        if (!active()) return
        const reply = (await api.qilingPoll(Boolean(props.bind), result.attempt, current.signal)).data
        if (!active()) return
        if (reply.status === 'pending') {
          pollTimer = setTimeout(poll, 3000)
          return
        }
        if (reply.status === 'expired') {
          expire()
          return
        }
        stop()
        if (reply.status === 'completed') emit('authenticated', reply.session)
        else if (reply.status === 'bound') emit('bound')
        else error.value = tr('扫码已结束，请重试')
      } catch (cause) {
        if (!active()) return
        stop()
        error.value = cause instanceof Error ? cause.message : tr('登录失败，请重试')
      }
    }
    pollTimer = setTimeout(poll, 3000)
  } catch (cause) {
    if (!active()) return
    stopRequests()
    busy.value = false
    error.value = cause instanceof Error ? cause.message : tr('登录失败，请重试')
  }
}

onMounted(() => { if (props.autoStart) void start() })
onBeforeUnmount(stop)
watch(() => auth.token, stop)
</script>

<template>
  <section class="qiling-login">
    <AppButton v-if="!attempt" type="button" variant="secondary" :loading="busy" @click="start">
      {{ bind ? tr('绑定器灵账号') : tr('使用器灵登录') }}
    </AppButton>
    <template v-else>
      <div v-if="qrImage || !qrUnavailable" class="qiling-login__code" :class="{ 'is-expired': expired }" :aria-busy="busy">
        <img v-if="qrImage" class="qiling-login__qr" :src="qrImage" :alt="expired ? '' : tr('器灵登录二维码')" width="224" height="224" />
        <AppButton v-if="expired && qrImage" class="qiling-login__refresh" type="button" :loading="busy" @click="start">
          <RefreshCw v-if="!busy" :size="19" aria-hidden="true" />
          <span>{{ tr('重新获取二维码') }}</span>
        </AppButton>
      </div>
      <p v-if="expired" role="status">{{ tr('二维码已过期') }}</p>
      <AppButton v-if="expired && !qrImage" type="button" variant="secondary" :loading="busy" @click="start">{{ tr('重新获取二维码') }}</AppButton>
      <template v-if="!expired">
        <p role="status">{{ qrImage ? tr('使用微信扫码') : qrUnavailable ? tr('无法显示二维码，请打开微信授权链接') : tr('等待微信授权') }}</p>
        <time class="qiling-login__countdown" role="timer" :aria-label="tr('二维码剩余时间')">{{ countdown }}</time>
        <a :href="attempt.authorization_url" target="_blank" rel="noopener noreferrer">{{ tr('在手机上打开授权') }} <ArrowUpRight :size="13" aria-hidden="true" /></a>
      </template>
      <AppButton v-if="bind || !autoStart" type="button" @click="stop">{{ tr('取消') }}</AppButton>
    </template>
    <p v-if="error" class="qiling-login__error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.qiling-login { display: grid; justify-items: start; gap: 8px; color: var(--app-text-secondary); }
.qiling-login__code { position: relative; isolation: isolate; width: var(--qiling-qr-size, 224px); max-width: 100%; aspect-ratio: 1; overflow: hidden; border-radius: 8px; background: var(--app-surface); }
.qiling-login__qr { display: block; width: 100%; height: auto; }
.qiling-login__code.is-expired .qiling-login__qr { filter: blur(9px); transform: scale(1.08); }
.qiling-login__refresh { position: absolute; inset: 0; width: 100%; height: 100%; display: grid; justify-items: center; align-content: center; gap: 8px; border-radius: inherit; background: rgb(12 17 30 / 74%); color: white; }
.qiling-login__refresh:hover:not(:disabled), .qiling-login__refresh:disabled { color: white; background: rgb(12 17 30 / 85%); }
.qiling-login__refresh:focus-visible { outline: 2px solid white; outline-offset: -4px; }
.qiling-login__countdown { font-variant-numeric: tabular-nums; font-size: 13px; }
.qiling-login p { margin: 0; }
.qiling-login a { display: inline-flex; align-items: center; gap: 3px; color: var(--app-accent); }
.qiling-login__error { color: var(--app-danger); }
</style>
