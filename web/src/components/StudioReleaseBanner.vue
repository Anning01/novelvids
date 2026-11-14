<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { API_BASE, request } from '@/api'
import { locale, tr } from '@/i18n'
import { useAuthStore } from '@/features/auth/authStore'
import { appConfirm } from '@/shared/confirmDialog'

interface Latest { online: boolean; version: string; required: string[]; summary: string; summary_en: string }
interface Status { installed: string; latest: Latest | null; updater: {phase: string; version?: string} | null }
const auth = useAuthStore()
const status = ref<Status>()
const stale = ref(false)
const busy = ref(false)
const error = ref('')
const dismissed = ref(localStorage.getItem('studio-release-dismissed'))
const pending = computed(() => ['preparing','draining','installing','rolling_back'].includes(status.value?.updater?.phase ?? ''))
const latest = computed(() => status.value?.latest)
const newer = computed(() => {
  if (!latest.value || !status.value) return false
  const current = status.value.installed.split('.').map(Number)
  const deltas = latest.value.version.split('.').map((v,i) => Number(v) - current[i]!)
  return (deltas.find(delta => delta !== 0) ?? 0) > 0
})
const required = computed(() => Boolean(latest.value?.required.length))
const failure = computed(() => ['rolled_back','failed','recovery_needed'].includes(status.value?.updater?.phase ?? ''))
const visible = computed(() => pending.value || stale.value || (newer.value && (required.value || dismissed.value !== latest.value?.version)))
let timer: ReturnType<typeof setTimeout>
let checking = false
let active = true
let checkedAt = 0
async function check() {
  clearTimeout(timer)
  if (!active || checking || document.visibilityState === 'hidden') return
  checking = true
  checkedAt = Date.now()
  try {
    const [info, build] = await Promise.allSettled([
      fetch(API_BASE + '/release', { cache: 'no-store', signal: AbortSignal.timeout(9000) }).then(r => r.json()),
      fetch(import.meta.env.BASE_URL + 'studio-build.json', { cache: 'no-store', signal: AbortSignal.timeout(9000) }).then(r => r.json()),
    ])
    if (!active) return
    if (info.status === 'fulfilled' && info.value.data?.installed) status.value = info.value.data
    if (build.status === 'fulfilled' && build.value.build && import.meta.env.VITE_STUDIO_BUILD)
      stale.value = build.value.build !== import.meta.env.VITE_STUDIO_BUILD
  } finally {
    checking = false
    if (active) timer = setTimeout(check, pending.value || busy.value ? 3000 : 60000)
  }
}
function visibility() { if (Date.now() - checkedAt >= 15000) void check() }
onMounted(() => { void check(); document.addEventListener('visibilitychange', visibility) })
onBeforeUnmount(() => { active = false; clearTimeout(timer); document.removeEventListener('visibilitychange', visibility) })
function dismiss() {
  dismissed.value = latest.value!.version
  localStorage.setItem('studio-release-dismissed', dismissed.value)
}
async function refresh() {
  if (!window.dispatchEvent(new Event('studio-before-refresh', { cancelable: true }))) {
    error.value = tr('分镜修改尚未保存，请保存后再刷新。')
    return
  }
  if (await appConfirm({ title: tr('刷新页面'), message: tr('确认当前编辑已保存，再载入新版页面。'),
    confirmLabel: tr('刷新页面'), cancelLabel: tr('继续编辑'), tone: 'neutral' })) {
    if (window.dispatchEvent(new Event('studio-before-refresh', { cancelable: true }))) window.location.reload()
    else error.value = tr('分镜修改尚未保存，请保存后再刷新。')
  }
}
async function upgrade() {
  if (!latest.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await request<{data: NonNullable<Status['updater']>}>('/release', {
      method: 'POST', body: JSON.stringify({ version: latest.value.version }),
    })
    if (status.value) status.value = { ...status.value, updater: result.data }
    void check()
  } catch (cause) { error.value = (cause as Error).message }
  finally { busy.value = false }
}
</script>

<template>
  <div v-if="visible" class="studio-release" role="region" :aria-label="tr('工作台更新')">
    <span role="status">
      <template v-if="pending">{{ status?.updater?.phase === 'preparing' ? tr('正在准备新版工作台') : status?.updater?.phase === 'draining' ? tr('等待后台任务完成') : status?.updater?.phase === 'rolling_back' ? tr('正在恢复上一版工作台') : tr('正在升级工作台') }}</template>
      <template v-else-if="stale">{{ tr('工作台已更新，保存当前编辑后可刷新页面。') }}</template>
      <template v-else-if="latest">
        <strong>{{ tr('工作台有新版本 {p0}', {p0: latest.version}) }}</strong>
        {{ locale === 'zh' ? latest.summary : latest.summary_en }}
        <template v-if="failure">{{ status?.updater?.phase === 'rolled_back' ? tr('升级失败，已恢复上一版。') : tr('升级失败，请管理员检查更新服务。') }}</template>
        <template v-if="required">{{ tr('使用新功能前需升级工作台。') }}</template>
        <template v-if="!auth.isSuperAdmin">{{ tr('请联系部署管理员升级。') }}</template>
      </template>
      <span v-if="error" role="alert">{{ error }}</span>
    </span>
    <template v-if="!pending">
      <button v-if="stale" type="button" @click="refresh">{{ tr('刷新页面') }}</button>
      <template v-else-if="auth.isSuperAdmin">
        <button v-if="latest?.online && status?.updater && status.updater.phase !== 'recovery_needed'" type="button" :disabled="busy" @click="upgrade">{{ tr('升级工作台') }}</button>
        <a v-else href="https://github.com/Anning01/novelvids#在线升级" target="_blank" rel="noopener">{{ tr('查看升级步骤') }}</a>
      </template>
      <button v-if="!stale && !required" type="button" @click="dismiss">{{ tr('收起此版本提醒') }}</button>
    </template>
  </div>
</template>

<style scoped>
.studio-release { display:flex; flex-wrap:wrap; align-items:center; gap:.4rem .85rem; padding:.55rem 1rem; flex:none; background:var(--app-surface,#fff); color:var(--app-text,#272936); border-bottom:1px solid var(--app-border,#dedee6); font-size:.875rem }
.studio-release > span { flex:1 1 20rem }
.studio-release button,.studio-release a { font:inherit; color:inherit; text-decoration:underline; background:transparent; border:0; cursor:pointer; padding:.3rem }
.studio-release button:focus-visible,.studio-release a:focus-visible { outline:2px solid currentColor }
</style>
