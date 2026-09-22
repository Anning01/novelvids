<script setup lang="ts">
import { computed, onMounted, ref, useId } from 'vue'
import { ElSwitch } from 'element-plus'
import 'element-plus/theme-chalk/el-switch.css'
import { Bot, ChevronDown, SlidersHorizontal } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import AppSettingsCard from '@/components/AppSettingsCard.vue'
import { notice } from '@/shared/notice'
import { agentApi } from './api'
import type { AgentConfiguration } from './types'

const formId = useId()
const configuration = ref<AgentConfiguration | null>(null)
const savedSnapshot = ref('')
const saving = ref(false)
const error = ref('')
const dirty = computed(() => Boolean(configuration.value && JSON.stringify(configuration.value) !== savedSnapshot.value))
interface BudgetField {
  key: Exclude<keyof AgentConfiguration, 'enabled'>
  label: string
  unit: string
  ratio?: boolean
}
const groups: { title: string; description: string; fields: BudgetField[] }[] = [
  { title: '对话用量', description: '默认按 DeepSeek 长上下文对话设置，仍受所选模型自身上限约束。', fields: [
    { key: 'max_targets', label: '最多修改对象', unit: '个 / 轮' },
    { key: 'request_limit', label: '模型调用上限', unit: '次 / 轮' },
    { key: 'tool_calls_limit', label: '工具调用上限', unit: '次 / 轮' },
    { key: 'timeout_seconds', label: '运行超时', unit: '秒' },
    { key: 'max_output_tokens', label: '单次输出上限', unit: 'token' },
    { key: 'total_tokens_limit', label: '每轮总用量上限', unit: 'token' },
  ] },
  { title: '记忆与上下文', description: '按 840K 输入预算管理工作区，达到 70% 时自动整理历史。', fields: [
    { key: 'working_input_tokens', label: '工作上下文预算', unit: '预估 token' },
    { key: 'max_context_characters', label: '上下文字符上限', unit: '字符' },
    { key: 'compaction_trigger_ratio', label: '整理触发比例', unit: '0–1', ratio: true },
    { key: 'compaction_target_ratio', label: '整理后目标比例', unit: '0–1', ratio: true },
    { key: 'history_runs', label: '近期对话轮数', unit: '轮' },
    { key: 'context_page_characters', label: '每页读取长度', unit: '字符' },
    { key: 'summary_output_tokens', label: '摘要输出上限', unit: 'token' },
    { key: 'summary_timeout_seconds', label: '摘要等待时间', unit: '秒' },
  ] },
]
onMounted(async () => {
  try {
    configuration.value = (await agentApi.configuration()).data
    savedSnapshot.value = JSON.stringify(configuration.value)
  } catch (caught) { error.value = (caught as Error).message }
})
async function save() {
  if (!configuration.value || saving.value) return
  saving.value = true
  error.value = ''
  try {
    configuration.value = (await agentApi.updateConfiguration(configuration.value)).data
    savedSnapshot.value = JSON.stringify(configuration.value)
    notice.success('创作助手配置已保存')
  } catch (caught) { error.value = (caught as Error).message }
  finally { saving.value = false }
}
</script>

<template>
  <AppSettingsCard class="agent-settings-panel" title="创作助手" description="让助手记住创作设定，通过对话完成调整。">
    <template #icon><Bot :size="20" /></template>
    <template #status><span class="agent-settings-panel__tag">对话创作</span></template>
    <p v-if="error" class="agent-settings-panel__error" role="alert">{{ error }}</p>
    <form v-if="configuration" :id="formId" @submit.prevent="save">
      <div class="agent-settings-panel__enable">
        <div><strong>启用创作助手</strong><p>在工作区中管理人物、场景、道具和分镜。</p></div>
        <ElSwitch v-model="configuration.enabled" aria-label="启用创作助手" :disabled="saving" />
      </div>
      <div class="agent-settings-panel__features" aria-label="助手能力">
        <span>跨对话记忆</span><span>自动整理上下文</span><span>修改可撤销</span>
      </div>
      <details class="agent-settings-panel__advanced">
        <summary><SlidersHorizontal :size="16" aria-hidden="true" /><span>高级设置<small>调用预算与运行限制</small></span><ChevronDown :size="16" class="agent-settings-panel__chevron" aria-hidden="true" /></summary>
        <div class="agent-settings-panel__groups">
          <fieldset v-for="group in groups" :key="group.title" :disabled="saving">
            <legend>{{ group.title }}</legend><p>{{ group.description }}</p>
            <div class="agent-settings-panel__fields">
              <label v-for="field in group.fields" :key="field.key"><span>{{ field.label }}</span>
                <span class="agent-settings-panel__input"><input v-model.number="configuration[field.key]" type="number" :min="field.ratio ? 0.01 : 1" :max="field.ratio ? 0.99 : undefined" :step="field.ratio ? 0.01 : 1" /><span aria-hidden="true">{{ field.unit }}</span></span>
              </label>
            </div>
          </fieldset>
        </div>
      </details>
    </form>
    <p v-else-if="!error" class="agent-settings-panel__loading" role="status">正在读取助手设置…</p>
    <template v-if="configuration" #footer>
      <span :class="{ 'agent-settings-panel__unsaved': dirty }">{{ dirty ? '有未保存的更改' : '更改将在保存后应用于下一轮对话' }}</span>
      <AppButton :form="formId" type="submit" variant="primary" size="sm" :loading="saving">保存助手配置</AppButton>
    </template>
  </AppSettingsCard>
</template>

<style scoped>
.agent-settings-panel { --el-switch-on-color: var(--app-accent); --el-switch-off-color: var(--app-border-strong); }
.agent-settings-panel__tag { padding: 4px 9px; border-radius: 6px; background: var(--app-surface-muted); color: var(--app-text-secondary); }
.agent-settings-panel__enable { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.agent-settings-panel__enable strong { font-size: 13px; font-weight: 600; }
.agent-settings-panel__enable p { margin: 5px 0 0; font-size: 12px; line-height: 1.6; color: var(--app-text-secondary); }
.agent-settings-panel :deep(.el-switch) { flex: 0 0 auto; --el-switch-on-color: var(--app-accent); --el-switch-off-color: var(--app-border-strong); }
.agent-settings-panel__features { display: flex; flex-wrap: wrap; gap: 8px 18px; padding: 16px 0 18px; font-size: 11px; color: var(--app-text-secondary); }
.agent-settings-panel__features span { display: inline-flex; align-items: center; gap: 7px; }
.agent-settings-panel__features span::before { content: ''; width: 4px; height: 4px; background: var(--app-accent); border-radius: 50%; }
.agent-settings-panel__advanced { border-top: 1px solid var(--app-border); }
summary { display: flex; align-items: center; gap: 10px; padding: 15px 0 0; list-style: none; cursor: pointer; color: var(--app-text-secondary); font-size: 12px; font-weight: 600; }
summary::-webkit-details-marker { display: none; }
summary > span { display: flex; align-items: baseline; gap: 10px; }
summary small { font-size: 11px; color: var(--app-text-muted); font-weight: 400; }
summary:hover { color: var(--app-accent); }
summary:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 4px; border-radius: 4px; }
.agent-settings-panel__chevron { margin-left: auto; transition: transform .16s ease; }
details[open] .agent-settings-panel__chevron { transform: rotate(180deg); }
.agent-settings-panel__groups { display: grid; gap: 24px; padding-top: 24px; }
fieldset { margin: 0; padding: 0; border: 0; min-width: 0; }
legend { padding: 0; font-size: 12px; font-weight: 650; }
fieldset > p { margin: 5px 0 14px; font-size: 11px; color: var(--app-text-secondary); }
.agent-settings-panel__fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 24px; }
label { display: grid; gap: 7px; font-size: 11px; color: var(--app-text-secondary); }
.agent-settings-panel__input { display: flex; align-items: center; gap: 8px; min-width: 0; border: 1px solid var(--app-border); border-radius: 8px; padding: 0 10px; background: var(--app-surface-muted); }
.agent-settings-panel__input:focus-within { border-color: var(--app-accent); box-shadow: 0 0 0 2px var(--app-accent-soft); }
.agent-settings-panel__input > span { white-space: nowrap; font-size: 10px; color: var(--app-text-muted); }
input { width: 100%; min-width: 0; height: 36px; padding: 0; border: 0; outline: 0; color: var(--app-text); background: transparent; font: inherit; font-size: 12px; font-variant-numeric: tabular-nums; }
.agent-settings-panel__error { margin: 0 0 14px; font-size: 12px; color: var(--app-danger, #c45461); }
.agent-settings-panel__loading { font-size: 12px; color: var(--app-text-secondary); }
.agent-settings-panel__unsaved { color: var(--app-accent); }
@media (max-width: 560px) { .agent-settings-panel__fields { grid-template-columns: 1fr; } summary small { display: none; } }
@media (prefers-reduced-motion: reduce) { .agent-settings-panel__chevron { transition: none; } }
</style>
