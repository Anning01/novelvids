<script setup lang="ts">
import { tr, dateLocale } from '@/i18n'

import { computed } from 'vue'
import AgentDisclosure from './AgentDisclosure.vue'
import { formatTokenCount } from '@/shared/tokenCount'

const props = defineProps<{ usage: Record<string, unknown> }>()
const number = (key: string) => typeof props.usage[key] === 'number' && Number.isFinite(props.usage[key]) ? Math.max(0, props.usage[key] as number) : 0
const cachedTokens = computed(() => Math.min(number('input_tokens'), number('cache_read_tokens')))
const uncachedTokens = computed(() => number('input_tokens') - cachedTokens.value)
const exactPair = (first: number, second: number) => `${first.toLocaleString(dateLocale.value)} / ${second.toLocaleString(dateLocale.value)} token`
const reported = computed(() => props.usage.cache_usage_reported === true)
const cacheRate = computed(() => number('input_tokens') > 0
  ? `${Math.min(100, 100 * number('cache_read_tokens') / number('input_tokens')).toFixed(1)}%` : '0.0%')
const rules = computed(() => Array.isArray(props.usage.remembered_rules)
  ? props.usage.remembered_rules.filter((item): item is { content: string; scope: { kind?: string } } =>
    typeof item === 'object' && item !== null && typeof item.content === 'string') : [])
const scopeName = (scope: { kind?: string }) => ({ get project() { return tr('项目') }, get chapter() { return tr('本章') }, get range() { return tr('指定章节') }, get targets() { return tr('指定对象') } })[scope.kind || ''] || tr('创作设定')
</script>

<template>
  <AgentDisclosure v-if="number('requests')" class="agent-usage" :title="tr('本轮用量')" :summary="number('compactions') ? tr('已整理上下文') : tr('{p0} 次调用', { p0: number('requests') })">
    <dl>
      <dt>{{ tr('模型调用') }}</dt><dd>{{ number('requests') }} {{ tr('次') }}<span v-if="number('summary_requests')">{{ tr('（含') }} {{ number('summary_requests') }} {{ tr('次摘要）') }}</span></dd>
      <template v-if="typeof usage.input_tokens === 'number' && typeof usage.output_tokens === 'number'"><dt>{{ tr('输入 / 输出') }}</dt><dd :title="exactPair(number('input_tokens'), number('output_tokens'))">{{ formatTokenCount(number('input_tokens')) }} / {{ formatTokenCount(number('output_tokens')) }} token</dd></template>
      <template v-if="reported"><dt>{{ tr('输入缓存命中') }}</dt><dd>{{ cacheRate }}</dd></template>
      <template v-if="reported"><dt>{{ tr('缓存 / 非缓存输入') }}</dt><dd :title="exactPair(cachedTokens, uncachedTokens)">{{ formatTokenCount(cachedTokens) }} / {{ formatTokenCount(uncachedTokens) }} token</dd></template>
    </dl>
  </AgentDisclosure>
  <AgentDisclosure v-if="rules.length" class="agent-usage" :title="tr('已记住 {p0} 条设定', { p0: rules.length })">
    <ul><li v-for="(rule, index) in rules" :key="index">{{ scopeName(rule.scope || {}) }}：{{ rule.content }}</li></ul>
  </AgentDisclosure>
</template>

<style scoped>
.agent-usage { margin: 2px 0 0; color: var(--app-text-secondary); font-size: 11px; line-height: 1.6; }
summary { cursor: pointer; width: fit-content; }
dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 10px; margin: 8px 0; }
dd { margin: 0; text-align: right; overflow-wrap: anywhere; }
p { margin: 6px 0; } ul { padding-left: 16px; }
</style>
