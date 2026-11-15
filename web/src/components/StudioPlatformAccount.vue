<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '@/api'
import { tr } from '@/i18n'
import AppButton from '@/components/AppButton.vue'

const props = defineProps<{ accountRevision?: number }>()
const account = ref<Awaited<ReturnType<typeof api.studioPlatformAccount>>['data'] | null>(null)
const accountLoading = ref(false)
const accountError = ref('')
let accountRequest = 0

async function loadAccount() {
  if (accountLoading.value) return
  const request = ++accountRequest
  accountLoading.value = true
  accountError.value = ''
  try {
    const { data } = await api.studioPlatformAccount()
    if (request === accountRequest) account.value = data
  } catch (reason) {
    if (request === accountRequest) accountError.value = reason instanceof Error ? reason.message : tr('平台账户加载失败')
  } finally {
    if (request === accountRequest) accountLoading.value = false
  }
}

watch(() => props.accountRevision, () => {
  ++accountRequest
  account.value = null
  accountError.value = ''
  accountLoading.value = false
  void loadAccount()
})

function refreshAccountOnFocus() {
  if (account.value) void loadAccount()
}
onMounted(() => {
  window.addEventListener('focus', refreshAccountOnFocus)
  void loadAccount()
})
onUnmounted(() => {
  ++accountRequest
  window.removeEventListener('focus', refreshAccountOnFocus)
})
</script>

<template>
  <section class="platform-account-settings">
    <div class="platform-account">
      <strong>{{ tr('API 平台账户') }}</strong>
      <span v-if="accountLoading && !account" role="status">{{ tr('加载中…') }}</span>
      <AppButton v-if="account || accountError" type="button" variant="ghost" size="sm" :loading="accountLoading" @click="loadAccount">{{ tr(accountError ? '重试' : '刷新余额') }}</AppButton>
      <template v-if="account"><span>{{ account.balance }} {{ account.currency }}</span><a :href="account.recharge_url" target="_blank" rel="noopener noreferrer">{{ tr('前往平台充值') }}</a></template>
      <p v-if="accountError" role="alert">{{ accountError }}</p>
    </div>
  </section>
</template>

<style scoped>
.platform-account-settings { padding:18px 22px 22px; color:var(--app-text); }
.platform-account { display:flex; flex-wrap:wrap; align-items:center; gap:14px; font-size:13px; }
a:focus-visible { outline:2px solid var(--app-accent); outline-offset:3px; }
a { color:var(--app-accent); }
p { font-size:13px; }
p[role="alert"] { color:var(--app-danger); }
</style>
