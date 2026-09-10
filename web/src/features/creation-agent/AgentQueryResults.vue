<script setup lang="ts">
import { LocateFixed, Plus } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import type { AgentQueryItem, AgentQueryResult } from './types'

defineProps<{ result: AgentQueryResult; disabled: boolean }>()
defineEmits<{ locate: [target: AgentQueryItem]; select: [target: AgentQueryItem] }>()
</script>

<template>
  <section class="agent-query-results" aria-label="查询结果">
    <header>找到 {{ result.total }} 个对象<span v-if="result.has_more"> · 当前显示 {{ result.items.length }} 个</span></header>
    <ul>
      <li v-for="item in result.items" :key="`${item.kind}:${item.id}`">
        <AppButton class="agent-query-results__name" size="xs" :title="item.name" @click="$emit('locate', item)"><LocateFixed :size="13" /><span>{{ item.name }}</span></AppButton>
        <AppButton v-if="item.kind !== 'chapter'" size="xs" icon-only :disabled="disabled" :aria-label="`指定${item.name}`" @click="$emit('select', item)"><Plus :size="14" /></AppButton>
      </li>
    </ul>
    <p v-if="!result.items.length">当前条件下没有匹配对象。</p>
    <p v-if="result.has_more">可以继续说“查看下一页”，或描述更具体的查找条件。</p>
  </section>
</template>

<style scoped>
.agent-query-results { min-width: 0; max-width: 100%; margin-top: 8px; padding: 10px; border: 1px solid var(--app-border); border-radius: 11px; font-size: 12px; }
header, p { color: var(--app-text-secondary); }p { margin: 8px 0 0; line-height: 1.6; }ul { margin: 6px 0 0; padding: 0; list-style: none; max-height: 240px; overflow: auto; }
li { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 4px; }.agent-query-results__name { flex: 1; min-width: 0; justify-content: flex-start; overflow: hidden; }.agent-query-results__name span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
