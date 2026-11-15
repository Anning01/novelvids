<script setup lang="ts">
import { tr } from '@/i18n'

import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Bot, RefreshCw, Settings2 } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { useAuthStore } from '@/features/auth/authStore'
import type { AgentCapabilities } from './types'

const props = defineProps<{ capabilities: AgentCapabilities | null; loading: boolean; error: string }>()
const emit = defineEmits<{ retry: [] }>()
const auth = useAuthStore()
const router = useRouter()
const title = computed(() => props.loading ? tr('正在连接你的创作助手') : !props.capabilities ? tr('暂时无法连接助手')
    : !props.capabilities.can_write ? tr('当前账号为只读权限') : tr('还需要配置一个对话模型'))
const description = computed(() => !props.capabilities ? tr('对话记录会保留，可以重新连接。')
    : !props.capabilities.can_write ? tr('你仍可查看自己的对话。修改画面需要管理员授予创作者权限。')
      : tr('在模型设置中添加支持工具调用的文本模型，然后回来重新连接。'))

</script>

<template>
  <section class="agent-setup" :aria-label="tr('助手连接状态')" :aria-busy="loading">
    <span class="agent-setup__icon"><Bot :size="25" /></span>
    <h3>{{ title }}</h3>
    <p v-if="!loading">{{ description }}</p>
    <p v-if="!capabilities && error" role="alert">{{ error }}</p>
    <template v-if="!loading">
      <AppButton v-if="capabilities?.can_write && !capabilities.models.length && auth.canAccessSettings" variant="primary" size="sm" @click="router.push('/settings')"><Settings2 :size="15" />{{ tr('前往模型设置') }}</AppButton>
      <AppButton variant="ghost" size="sm" @click="emit('retry')"><RefreshCw :size="14" />{{ tr('重新连接') }}</AppButton>
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
