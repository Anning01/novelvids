<script setup lang="ts">
import { computed } from 'vue'
import { tr } from '@/i18n'
import AppButton from '@/components/AppButton.vue'
import type { AgentRecovery } from './types'

const props = defineProps<{ recovery: AgentRecovery; failed: boolean; disabled: boolean }>()
defineEmits<{ resume: [] }>()
const step = computed(() => ({ planning_request: '理解要求', source_reading: '阅读原文', creation_planning: '制定方案',
  assets: '资产提取', storyboard: '分镜生成', structured: '内容生成', creative_check: '内容检查', conversation: '处理修改',
} as Record<string, string>)[props.recovery.failure_step || ''] || '内容检查')
</script>

<template>
  <div v-if="failed || recovery.pending_count" class="agent-recovery" role="status">
    <p>{{ tr('未完成步骤') }}：{{ tr(step) }}</p>
    <p v-if="recovery.reusable_count">{{ tr('已保留 {p0} 项合格候选，待修正 {p1} 项', { p0: recovery.reusable_count, p1: recovery.pending_count }) }}</p>
    <p v-if="recovery.responses_saved">{{ tr('模型调用记录已保存，可检查本轮用量。') }}</p>
    <AppButton v-if="recovery.can_resume" size="xs" :disabled="disabled" @click="$emit('resume')">{{ tr('复用已完成步骤并继续') }}</AppButton>
  </div>
</template>

<style scoped>
.agent-recovery { padding: 8px 10px; border: 1px solid var(--app-border); border-radius: 8px; background: var(--app-surface); color: var(--app-text-secondary); font-size: 12px; }
p { margin: 4px 0; }
</style>
