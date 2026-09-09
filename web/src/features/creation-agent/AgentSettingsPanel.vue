<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppButton from '@/components/AppButton.vue'
import { notice } from '@/shared/notice'
import { agentApi } from './api'
import type { AgentConfiguration } from './types'

const configuration = ref<AgentConfiguration | null>(null)
const saving = ref(false)
const error = ref('')
const fields: { key: Exclude<keyof AgentConfiguration, 'enabled'>; label: string }[] = [
  { key: 'request_limit', label: '每轮模型调用上限' }, { key: 'tool_calls_limit', label: '每轮工具调用上限' },
  { key: 'max_targets', label: '每轮最多修改对象数' }, { key: 'timeout_seconds', label: '运行超时（秒）' },
  { key: 'max_context_characters', label: '上下文字符预算' }, { key: 'history_runs', label: '保留近期对话轮数' },
  { key: 'max_output_tokens', label: '单次输出 token 上限' }, { key: 'total_tokens_limit', label: '每轮总 token 上限' },
]
onMounted(async () => {
  try { configuration.value = (await agentApi.configuration()).data }
  catch (caught) { error.value = (caught as Error).message }
})
async function save() {
  if (!configuration.value) return
  saving.value = true
  try { configuration.value = (await agentApi.updateConfiguration(configuration.value)).data; notice.success('创作助手配置已保存') }
  catch (caught) { error.value = (caught as Error).message }
  finally { saving.value = false }
}
</script>

<template>
  <article class="agent-settings-panel">
    <h2>创作助手</h2>
    <p>只允许修改图片与分镜提示词。请先在模型配置中选择“创作助手”用途，并启用工具调用能力。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <form v-if="configuration" @submit.prevent="save">
      <label class="agent-settings-panel__enable"><input v-model="configuration.enabled" type="checkbox" role="switch" />启用创作助手</label>
      <details><summary>调用预算与运行限制</summary><div class="agent-settings-panel__fields">
        <label v-for="field in fields" :key="field.key">{{ field.label }}<input v-model.number="configuration[field.key]" type="number" min="1" required /></label>
      </div></details>
      <AppButton type="submit" variant="primary" :loading="saving">保存助手配置</AppButton>
    </form>
  </article>
</template>

<style scoped>
.agent-settings-panel { margin-top: 20px; padding: 24px; border: 1px solid var(--app-border); border-radius: 18px; background: var(--app-surface); color: var(--app-text); }
h2 { font-size: 18px; margin: 0 0 10px; } p { color: var(--app-text-secondary); font-size: 13px; line-height: 1.7; }
.agent-settings-panel__enable { display: flex; gap: 8px; align-items: center; padding: 12px 0; }
input { color: var(--app-text); background: var(--app-surface-muted); border: 1px solid var(--app-border); border-radius: 8px; padding: 8px; font: inherit; accent-color: var(--app-accent); }
details { margin: 10px 0 20px; } summary { cursor: pointer; }
.agent-settings-panel__fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 12px; }
.agent-settings-panel__fields label { display: grid; gap: 6px; font-size: 13px; }
</style>
