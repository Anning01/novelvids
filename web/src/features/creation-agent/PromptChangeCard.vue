<script setup lang="ts">
import { tr } from '@/i18n'

import { computed, ref } from 'vue'
import { CornerUpLeft, LocateFixed } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import AgentDisclosure from './AgentDisclosure.vue'
import type { AgentChange, AgentChangeItem } from './types'

const props = defineProps<{ change: AgentChange; canUndo: boolean }>()
const emit = defineEmits<{ undo: [id: number]; locate: [target: AgentChangeItem] }>()
const expanded = ref(false)
const operations = { get create() { return tr('已新增') }, get update() { return tr('已修改') }, get delete() { return tr('已移除') } }
const summary = computed(() => props.change.reverted_at ? tr('已撤销') : [...new Set(props.change.changes.map(item => item.operation ? operations[item.operation] : tr('已保存')))].join('、'))
const removed = (target: AgentChangeItem) => props.change.reverted_at ? target.operation === 'create' : target.operation === 'delete'
const labels: Record<string, string> = { get canonical_name() { return tr('名称') }, get name() { return tr('形态名称') }, get aliases() { return tr('别名') }, get description() { return tr('描述') },
  get base_traits() { return tr('图片提示词') }, prompt: '分镜提示词', get duration() { return tr('时长') }, get source_chapters() { return tr('适用章节') }, get chapter_numbers() { return tr('适用章节') },
  get is_global() { return tr('全书共用') }, get asset_ids() { return tr('出镜设定') }, get variant_bindings() { return tr('形态绑定') } }
function text(value: Record<string, unknown>) {
  return Object.entries(value).filter(([key]) => key in labels).map(([key, content]) => {
    const displayed = key === 'asset_ids' && Array.isArray(content) ? tr('{p0} 个设定', { p0: content.length })
      : key === 'variant_bindings' && content && typeof content === 'object' ? tr('{p0} 个指定形态', { p0: Object.keys(content).length })
        : typeof content === 'boolean' ? content ? tr('是') : tr('否') : Array.isArray(content) ? content.join('、') : String(content ?? tr('空'))
    return `${labels[key]}：${displayed}`
  }).join('\n\n')
}
</script>

<template>
  <section class="prompt-change-card" :aria-label="tr('修改记录 {p0}', { p0: props.change.id })">
    <AgentDisclosure v-model:open="expanded" :title="tr('{p0} · {p1} 项操作', { p0: summary, p1: change.changes.length })" :summary="tr('查看差异')">
      <template #actions><AppButton v-if="!change.reverted_at && canUndo" size="xs" icon-only :aria-label="tr('撤销这次修改')" :title="tr('撤销这次修改')" @click="emit('undo', change.id)"><CornerUpLeft :size="13" /></AppButton></template>
    <div class="prompt-change-card__details">
      <div v-for="(target, index) in change.changes" :key="`${target.kind}-${target.target_id}-${index}`">
        <strong v-if="removed(target)">{{ target.target_label || tr('已移除对象') }}</strong>
        <AppButton v-else size="xs" @click="emit('locate', target)"><LocateFixed :size="13" />{{ target.target_label || (target.kind === 'scene' ? tr('查看分镜') : tr('查看图片设定')) }}</AppButton>
        <template v-if="target.operation !== 'create'"><label>{{ target.operation === 'delete' ? tr('移除前的内容') : tr('修改前') }}</label><pre>{{ text(target.before) || tr('空内容') }}</pre></template>
        <template v-if="target.operation !== 'delete'"><label>{{ target.operation === 'create' ? tr('新增内容') : tr('修改后') }}</label><pre>{{ text(target.after) }}</pre></template>
        <p v-if="target.recovery?.order_before">{{ tr('已同步调整本章分镜顺序。') }}</p>
        <p v-if="target.operation === 'delete' && !change.reverted_at">{{ tr('原有媒体保留，可撤销恢复。') }}</p>
      </div>
    </div>
    </AgentDisclosure>
  </section>
</template>

<style scoped>
.prompt-change-card { margin-top: 4px; padding: 0 7px; border: 1px solid var(--app-border); border-radius: 8px; background: var(--app-surface); font-size: 12px; }
.prompt-change-card__heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.prompt-change-card__details { margin: 2px 0; }
label { display: block; margin: 8px 0 4px; color: var(--app-text-secondary); }
pre { max-height: 240px; overflow: auto; margin: 0; padding: 8px; background: var(--app-surface-muted); white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.6; }
</style>
