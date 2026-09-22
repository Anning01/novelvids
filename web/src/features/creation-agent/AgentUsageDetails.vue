<script setup lang="ts">
import { computed } from 'vue'
import AgentDisclosure from './AgentDisclosure.vue'

const props = defineProps<{ usage: Record<string, unknown> }>()
const number = (key: string) => typeof props.usage[key] === 'number' ? props.usage[key] as number : 0
const reported = computed(() => props.usage.cache_usage_reported === true)
const cacheRate = computed(() => number('input_tokens') > 0
  ? `${Math.min(100, 100 * number('cache_read_tokens') / number('input_tokens')).toFixed(1)}%` : '0.0%')
const rules = computed(() => Array.isArray(props.usage.remembered_rules)
  ? props.usage.remembered_rules.filter((item): item is { content: string; scope: { kind?: string } } =>
    typeof item === 'object' && item !== null && typeof item.content === 'string') : [])
const scopeName = (scope: { kind?: string }) => ({ project: '项目', chapter: '本章', range: '指定章节', targets: '指定对象' })[scope.kind || ''] || '创作设定'
</script>

<template>
  <AgentDisclosure v-if="number('requests')" class="agent-usage" title="本轮用量" :summary="number('compactions') ? '已整理上下文' : `${number('requests')} 次调用`">
    <dl>
      <dt>模型调用</dt><dd>{{ number('requests') }} 次<span v-if="number('summary_requests')">（含 {{ number('summary_requests') }} 次摘要）</span></dd>
      <dt>输入 / 输出</dt><dd>{{ number('input_tokens').toLocaleString() }} / {{ number('output_tokens').toLocaleString() }} token</dd>
      <dt>输入缓存命中</dt><dd>{{ reported ? cacheRate : '供应商未完整报告' }}</dd>
      <template v-if="reported"><dt>缓存 / 非缓存输入</dt><dd>{{ number('cache_read_tokens').toLocaleString() }} / {{ Math.max(0, number('input_tokens') - number('cache_read_tokens')).toLocaleString() }} token</dd></template>
    </dl>
    <p v-if="usage.cache_price_configured === false">尚未配置缓存输入单价，费用按当前模型价格计算。</p>
    <p v-if="usage.missing_usage">部分请求未返回完整用量。</p>
  </AgentDisclosure>
  <AgentDisclosure v-if="rules.length" class="agent-usage" :title="`已记住 ${rules.length} 条设定`">
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
