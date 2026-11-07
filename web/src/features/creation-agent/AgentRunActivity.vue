<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Check, ChevronRight, Circle, CircleAlert, Clock3, LoaderCircle } from 'lucide-vue-next'
import { tr } from '@/i18n'
import AgentActivity from './AgentActivity.vue'
import { creationAgentToolOperationLabel, creationAgentToolProgressLabel } from './toolPresentation'
import type { AgentActivityStep } from './types'

const props = defineProps<{
  status: number
  steps?: AgentActivityStep[]
  startedAt?: string | null
  finishedAt?: string | null
  statusText?: string
  operationLabel?: string
}>()
const active = computed(() => [1, 2, 6].includes(props.status))
const expanded = ref(active.value)
watch(active, running => { expanded.value = running })
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined
watch(active, running => {
  clearInterval(timer)
  now.value = Date.now()
  if (running) timer = setInterval(() => { now.value = Date.now() }, 1000)
}, { immediate: true })
onBeforeUnmount(() => clearInterval(timer))

function duration(start?: string | null, finish?: string | null): string {
  if (!start || (!active.value && !finish)) return ''
  const milliseconds = (finish ? Date.parse(finish) : now.value) - Date.parse(start)
  if (!Number.isFinite(milliseconds)) return ''
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  return seconds < 60 ? tr('{p0} 秒', { p0: seconds })
    : tr('{p0} 分 {p1} 秒', { p0: Math.floor(seconds / 60), p1: seconds % 60 })
}
const elapsed = computed(() => duration(props.startedAt, props.finishedAt))
const activeStepLabel = computed(() => {
  const step = [...(props.steps || [])].reverse().find(item => item.status === 'running')
  return step?.tool_name ? creationAgentToolProgressLabel(step.tool_name) : step ? tr(step.label) : ''
})
const stateText = computed(() => active.value ? (activeStepLabel.value || props.statusText || tr('正在处理你的创作要求'))
  : tr(({ 3: '已完成', 4: '本轮未完成', 5: '本轮已停止' } as Record<number, string>)[props.status] || '等待中'))
const summaryText = computed(() => props.operationLabel && !active.value ? `${props.operationLabel} · ${stateText.value}` : stateText.value)
function stepState(step: AgentActivityStep): string {
  return tr(step.status === 'completed' ? '已完成' : step.status === 'failed' ? '失败' : active.value ? '处理中' : '已结束')
}
</script>

<template>
  <section class="agent-run-activity" :aria-label="tr('执行过程')">
    <component :is="steps?.length ? 'button' : 'div'" class="agent-run-activity__header" :type="steps?.length ? 'button' : undefined" :aria-expanded="steps?.length ? expanded : undefined" :aria-label="steps?.length ? tr('执行过程') : undefined" @click="expanded = !expanded">
      <ChevronRight v-if="steps?.length" :size="12" class="agent-run-activity__chevron" :class="{ 'is-expanded': expanded }" aria-hidden="true" />
      <AgentActivity :text="summaryText" :active="active" />
      <span v-if="elapsed" class="agent-run-activity__elapsed"><Clock3 :size="12" aria-hidden="true" />{{ tr('用时 {p0}', { p0: elapsed }) }}</span>
    </component>
    <ol v-if="steps?.length && expanded" class="agent-run-activity__steps">
      <li v-for="step in steps" :key="step.id" class="agent-run-activity__step" :class="{ 'is-running': step.status === 'running' && active, 'is-failed': step.status === 'failed' }">
        <Check v-if="step.status === 'completed'" class="agent-run-activity__icon" :size="13" aria-hidden="true" />
        <CircleAlert v-else-if="step.status === 'failed'" class="agent-run-activity__icon" :size="13" aria-hidden="true" />
        <LoaderCircle v-else-if="active" class="agent-run-activity__icon agent-run-activity__spinner" :size="13" aria-hidden="true" />
        <Circle v-else class="agent-run-activity__icon" :size="13" aria-hidden="true" />
        <div class="agent-run-activity__body">
          <details v-if="step.detail" :open="step.status === 'running' && active" class="agent-run-activity__detail">
            <summary><span>{{ step.tool_name ? creationAgentToolOperationLabel(step.tool_name) : tr(step.label) }}</span><span class="agent-run-activity__step-state">{{ stepState(step) }}</span></summary>
            <p>{{ step.detail }}</p>
          </details>
          <div v-else class="agent-run-activity__step-heading"><span>{{ step.tool_name ? creationAgentToolOperationLabel(step.tool_name) : tr(step.label) }}</span><span class="agent-run-activity__step-state">{{ stepState(step) }}</span></div>
          <span v-if="step.started_at && step.finished_at" class="agent-run-activity__step-time">{{ duration(step.started_at, step.finished_at) }}</span>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.agent-run-activity { margin: 2px 0 8px; min-width: 0; color: var(--app-text-secondary); font-size: 12px; }
.agent-run-activity__header { display: flex; align-items: center; gap: 7px; padding: 4px 0; width: fit-content; max-width: 100%; border: 0; background: transparent; color: inherit; font: inherit; text-align: left; }
button.agent-run-activity__header { cursor: pointer; border-radius: 4px; }
button.agent-run-activity__header:hover { color: var(--app-text); }
button.agent-run-activity__header:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 3px; }
.agent-run-activity__chevron { flex-shrink: 0; transition: transform .15s; }
.agent-run-activity__chevron.is-expanded { transform: rotate(90deg); }
.agent-run-activity__elapsed { display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0; margin-left: 5px; font-size: 11px; font-variant-numeric: tabular-nums; }
.agent-run-activity__steps { list-style: none; padding: 0; margin: 0 0 0 6px; }
.agent-run-activity__step { position: relative; display: flex; gap: 10px; padding: 4px 0 8px 13px; border-left: 1px solid var(--app-border); }
.agent-run-activity__step:last-child { padding-bottom: 2px; border-left-color: transparent; }
.agent-run-activity__icon { position: absolute; left: -7px; top: 6px; flex-shrink: 0; background: var(--app-surface); }
.agent-run-activity__body { min-width: 0; width: 100%; }
.agent-run-activity__step-heading, .agent-run-activity__detail summary { line-height: 1.65; overflow-wrap: anywhere; }
.agent-run-activity__step-state { margin-left: 8px; font-size: 10px; color: var(--app-text-secondary); white-space: nowrap; }
.agent-run-activity__step-time { font-size: 10px; font-variant-numeric: tabular-nums; }
.agent-run-activity__detail summary { padding: 1px 4px; margin: -1px -4px; border-radius: 4px; cursor: pointer; }
.agent-run-activity__detail summary:hover { color: var(--app-text); background: var(--app-surface-hover); }
.agent-run-activity__detail summary:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.agent-run-activity__detail p { margin: 5px 0 2px; padding-left: 8px; border-left: 2px solid var(--app-border); color: var(--app-text-secondary); line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 220px; overflow-y: auto; }
.is-running { color: var(--app-text); }
.is-failed { color: var(--creation-danger); }
.agent-run-activity__spinner { animation: agent-step-spin 1.2s linear infinite; }
@keyframes agent-step-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .agent-run-activity__chevron { transition: none; } .agent-run-activity__spinner { animation: none; } }
</style>
