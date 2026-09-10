<script setup lang="ts">
import { computed, ref } from 'vue'
import { CornerUpLeft, LocateFixed } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import type { AgentChange, AgentChangeItem } from './types'

const props = defineProps<{ change: AgentChange; canUndo: boolean }>()
const emit = defineEmits<{ undo: [id: number]; locate: [target: AgentChangeItem] }>()
const expanded = ref(false)
const operations = { create: '已新增', update: '已修改', delete: '已移除' }
const summary = computed(() => props.change.reverted_at ? '已撤销' : [...new Set(props.change.changes.map(item => item.operation ? operations[item.operation] : '已保存'))].join('、'))
const removed = (target: AgentChangeItem) => props.change.reverted_at ? target.operation === 'create' : target.operation === 'delete'
const labels: Record<string, string> = { canonical_name: '名称', name: '形态名称', aliases: '别名', description: '描述',
  base_traits: '图片提示词', prompt: '分镜提示词', duration: '时长', source_chapters: '适用章节', chapter_numbers: '适用章节',
  is_global: '全书共用', asset_ids: '出镜设定', variant_bindings: '形态绑定' }
function text(value: Record<string, unknown>) {
  return Object.entries(value).filter(([key]) => key in labels).map(([key, content]) => {
    const displayed = key === 'asset_ids' && Array.isArray(content) ? `${content.length} 个设定`
      : key === 'variant_bindings' && content && typeof content === 'object' ? `${Object.keys(content).length} 个指定形态`
        : typeof content === 'boolean' ? content ? '是' : '否' : Array.isArray(content) ? content.join('、') : String(content ?? '空')
    return `${labels[key]}：${displayed}`
  }).join('\n\n')
}
</script>

<template>
  <section class="prompt-change-card" :aria-label="`修改记录 ${props.change.id}`">
    <div class="prompt-change-card__heading">
      <span>{{ summary }} · {{ change.changes.length }} 项操作</span>
      <AppButton size="xs" :aria-expanded="expanded" @click="expanded = !expanded">{{ expanded ? '收起差异' : '查看差异' }}</AppButton>
    </div>
    <div v-if="expanded" class="prompt-change-card__details">
      <div v-for="(target, index) in change.changes" :key="`${target.kind}-${target.target_id}-${index}`">
        <strong v-if="removed(target)">{{ target.target_label || '已移除对象' }}</strong>
        <AppButton v-else size="xs" @click="emit('locate', target)"><LocateFixed :size="13" />{{ target.target_label || (target.kind === 'scene' ? '查看分镜' : '查看图片设定') }}</AppButton>
        <template v-if="target.operation !== 'create'"><label>{{ target.operation === 'delete' ? '移除前的内容' : '修改前' }}</label><pre>{{ text(target.before) || '空内容' }}</pre></template>
        <template v-if="target.operation !== 'delete'"><label>{{ target.operation === 'create' ? '新增内容' : '修改后' }}</label><pre>{{ text(target.after) }}</pre></template>
        <p v-if="target.recovery?.order_before">已同步调整本章分镜顺序。</p>
        <p v-if="target.operation === 'delete' && !change.reverted_at">原有媒体保留，可撤销恢复。</p>
      </div>
    </div>
    <AppButton v-if="!change.reverted_at && canUndo" size="xs" @click="emit('undo', change.id)"><CornerUpLeft :size="13" />撤销这次修改</AppButton>
  </section>
</template>

<style scoped>
.prompt-change-card { margin-top: 8px; padding: 10px; border: 1px solid var(--app-border); border-radius: 11px; background: var(--app-surface); font-size: 12px; }
.prompt-change-card__heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.prompt-change-card__details { margin: 10px 0; }
label { display: block; margin: 8px 0 4px; color: var(--app-text-secondary); }
pre { max-height: 240px; overflow: auto; margin: 0; padding: 8px; background: var(--app-surface-muted); white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.6; }
</style>
