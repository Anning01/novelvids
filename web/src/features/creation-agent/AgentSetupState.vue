<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Bot, RefreshCw, Settings2 } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { agentApi } from './api'
import type { AgentCapabilities } from './types'

const props = defineProps<{ capabilities: AgentCapabilities | null; loading: boolean; error: string }>()
const emit = defineEmits<{ retry: [] }>()
const auth = useAuthStore()
const router = useRouter()
const enabling = ref(false)
const setupError = ref('')
const canConfigure = computed(() => auth.enabled === false || auth.isSuperAdmin)
const title = computed(() => props.loading ? '正在连接你的创作助手' : !props.capabilities ? '暂时无法连接助手'
  : !props.capabilities.enabled ? '创作助手尚未启用'
    : !props.capabilities.can_write ? '当前账号为只读权限' : '还需要配置一个对话模型')
const description = computed(() => !props.capabilities ? '对话记录会保留，可以重新连接。'
  : !props.capabilities.enabled ? canConfigure.value ? '开启后，选择资产或分镜，说出想调整的内容即可。' : '请联系管理员开启创作助手，开启后可在这里继续。'
    : !props.capabilities.can_write ? '你仍可查看自己的对话。修改画面需要管理员授予创作者权限。'
      : '在模型设置中添加支持工具调用的文本模型，然后回来重新连接。')

async function enable() {
  enabling.value = true
  setupError.value = ''
  try {
    const config = await agentApi.configuration()
    await agentApi.updateConfiguration({ ...config.data, enabled: true })
    emit('retry')
  } catch (error) { setupError.value = error instanceof Error ? error.message : '启用失败，请重试' }
  finally { enabling.value = false }
}
</script>

<template>
  <section class="agent-setup" aria-label="助手连接状态" :aria-busy="loading || enabling">
    <span class="agent-setup__icon"><Bot :size="25" /></span>
    <h3>{{ title }}</h3>
    <p v-if="!loading">{{ description }}</p>
    <p v-if="setupError || (!capabilities && error)" role="alert">{{ setupError || error }}</p>
    <template v-if="!loading">
      <AppButton v-if="capabilities && !capabilities.enabled && canConfigure" variant="primary" size="sm" :loading="enabling" @click="enable">启用创作助手</AppButton>
      <AppButton v-else-if="capabilities?.enabled && capabilities.can_write && !capabilities.models.length && auth.canAccessSettings" variant="primary" size="sm" @click="router.push('/settings')"><Settings2 :size="15" />前往模型设置</AppButton>
      <AppButton variant="ghost" size="sm" :disabled="enabling" @click="emit('retry')"><RefreshCw :size="14" />重新连接</AppButton>
    </template>
  </section>
</template>

<style scoped>
.agent-setup { display: flex; flex: 1; min-height: 220px; flex-direction: column; align-items: flex-start; justify-content: center; gap: 12px; padding: 28px 24px; }
.agent-setup__icon { display: grid; width: 48px; height: 48px; place-items: center; color: var(--app-accent); background: var(--app-accent-soft); border-radius: 15px; }
.agent-setup h3 { margin: 0; font-size: 16px; }
.agent-setup p { margin: 0; color: var(--app-text-secondary); font-size: 13px; line-height: 1.8; }
.agent-setup p[role=alert] { color: var(--app-danger, #b65361); }
</style>
