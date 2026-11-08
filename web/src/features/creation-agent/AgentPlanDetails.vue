<script setup lang="ts">
import { tr } from '@/i18n'
import type { PendingProduction } from './types'

defineProps<{ plan: PendingProduction }>()
const operationLabel = (operation: string) => tr(({ assets: '资产提取', storyboard: '分镜生成', image: '图片生成', video: '视频生成' } as Record<string, string>)[operation] || operation)
</script>

<template>
  <section class="agent-plan" :aria-label="tr('创作方案')">
    <p class="agent-plan__summary">{{ plan.summary }}</p>
    <details v-if="plan.read_chapters?.length" class="agent-plan__sources">
      <summary>{{ tr('参考章节') }} · {{ plan.read_chapters.length }}</summary>
      <ul><li v-for="chapter in plan.read_chapters" :key="chapter">{{ chapter }}</li></ul>
    </details>
    <ol>
      <li v-for="(step, index) in plan.labels" :key="index">
        <details>
          <summary>
            <span>{{ operationLabel(step.operation) }} · {{ step.target_label }}</span>
            <small>{{ tr(step.mode === 'revise' ? '调整已有内容' : step.mode === 'regenerate' ? '使用已有提示词重新生成' : '保留已有，补齐缺失') }}</small>
          </summary>
          <p v-if="step.instructions">{{ step.instructions }}</p>
        </details>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.agent-plan { color: var(--app-text); font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
.agent-plan__summary { margin: 0 0 10px; white-space: pre-wrap; }
.agent-plan ul, .agent-plan ol { margin: 6px 0; padding-left: 22px; }
.agent-plan li + li { margin-top: 6px; }
.agent-plan details { border: 1px solid var(--app-border); border-radius: 8px; background: var(--app-surface); }
.agent-plan summary { cursor: pointer; min-height: 44px; padding: 8px 10px; }
.agent-plan summary:hover { background: var(--app-surface-hover); }
.agent-plan summary:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.agent-plan small { display: block; color: var(--app-text-secondary); font-size: 12px; }
.agent-plan details p { padding: 0 10px 10px; margin: 0; white-space: pre-wrap; }
</style>
